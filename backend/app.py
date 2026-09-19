# -*- coding: utf-8 -*-
# CineSculpt backend main service
import os
import sys
import uuid
import json
import time
import subprocess
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
# 内存优化：不再在 Web 进程顶层 import reconstruct/segment/describe/mesh_ops——
# 它们会连带加载 numpy/trimesh/scipy（约 100-150MB）。这些模块只在生成子进程里用，
# Web 进程仅在微调/修理接口时才惰性加载 mesh_ops，避免 Web+子进程双份内存挤爆 512MB。

app = Flask(__name__)
CORS(app)

BASE = os.path.dirname(os.path.abspath(__file__))
UPLOAD = os.path.join(BASE, "..", "uploads")
OUTPUT = os.path.join(BASE, "..", "output")
FRONTEND = os.path.join(BASE, "..", "frontend")
os.makedirs(UPLOAD, exist_ok=True)
os.makedirs(OUTPUT, exist_ok=True)

ALLOWED = {"png", "jpg", "jpeg", "bmp", "tiff", "tif"}
SESSIONS = {}
JOBS = {}  # sid -> {"status": "processing"|"done"|"error", ...}
APP_VERSION = "20260920-2"  # 用于在 /api/status 确认最新代码已部署（修复成功时多图回退原因被覆盖丢弃）

# 重启诊断：boot_count 在同容器内递增；若变回 1，说明容器被整体替换（磁盘被清空）
BOOT_TIME = time.strftime("%Y-%m-%d %H:%M:%S")
try:
    _bc = int(open(os.path.join(OUTPUT, "boot_count.txt")).read().strip() or "0")
except Exception:
    _bc = 0
BOOT_COUNT = _bc + 1
try:
    with open(os.path.join(OUTPUT, "boot_count.txt"), "w") as _f:
        _f.write(str(BOOT_COUNT))
except Exception:
    pass

def allowed(fn):
    return "." in fn and fn.rsplit(".", 1)[1].lower() in ALLOWED

def get_session_images(sid):
    """优先取内存会话；进程重启/重新部署导致内存丢失时，从磁盘恢复。
    上传的图片本身就落在 uploads/<sid>/ 目录，重启后仍在，可直接重建会话。"""
    sess = SESSIONS.get(sid)
    if sess and sess.get("images"):
        return sess["images"]
    sdir = os.path.join(UPLOAD, sid)
    if os.path.isdir(sdir):
        imgs = [os.path.join(sdir, f) for f in sorted(os.listdir(sdir))
                if os.path.isfile(os.path.join(sdir, f)) and allowed(f)]
        if imgs:
            SESSIONS[sid] = {"images": imgs}
            return imgs
    return None

@app.route("/")
def index():
    return send_from_directory(FRONTEND, "index.html")

@app.route("/<path:fn>")
def static_files(fn):
    return send_from_directory(FRONTEND, fn)

@app.route("/api/upload", methods=["POST"])
def api_upload():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "没有选择文件"}), 400
    if len(files) > 5:
        return jsonify({"error": "最多上传 5 张"}), 400
    sid = str(uuid.uuid4())
    sdir = os.path.join(UPLOAD, sid)
    os.makedirs(sdir, exist_ok=True)
    saved = []
    for f in files:
        if f.filename and allowed(f.filename):
            ext = f.filename.rsplit(".", 1)[1].lower()
            p = os.path.join(sdir, str(len(saved)) + "." + ext)
            f.save(p)
            saved.append(p)
    if not saved:
        return jsonify({"error": "没有有效的图片（支持 JPG/PNG/BMP/TIFF）"}), 400
    SESSIONS[sid] = {"images": saved}
    return jsonify({"success": True, "session_id": sid, "count": len(saved)})

@app.route("/api/reconstruct", methods=["POST"])
def api_reconstruct():
    data = request.get_json(force=True)
    sid = data.get("session_id")
    mode = data.get("mode", "hero")
    keep_subject = data.get("keep_subject", mode == "hero")
    source_text = (data.get("source_text") or "").strip()
    # 透传用户在前端填写的密钥（不依赖服务器环境变量，访客可自带 Key）
    tripo_key = (data.get("tripo_key") or "").strip()
    llm_key = (data.get("llm_key") or "").strip()
    llm_base = (data.get("llm_base") or "").strip()
    llm_model = (data.get("llm_model") or "").strip()
    # 校验 sid 格式（防路径穿越），并支持重启后从磁盘恢复会话
    try:
        uuid.UUID(str(sid))
    except (ValueError, TypeError, AttributeError):
        return jsonify({"error": "会话不存在，请重新上传"}), 404
    images = get_session_images(sid)
    if not images:
        return jsonify({"error": "会话不存在，请重新上传"}), 404
    # 关键修复：在独立子进程中执行耗内存的生成任务。
    # 主 Web 进程保持轻量，随时响应平台健康检查，绝不会因生成任务被重启。
    # 即使子进程因内存被系统杀掉，Web 服务仍在线，前端会显示“生成失败”而非整站崩溃。
    result_path = os.path.join(OUTPUT, sid + "_job.json")
    if os.path.exists(result_path):
        os.remove(result_path)
    try:
        log_f = open(os.path.join(OUTPUT, sid + "_worker.log"), "w")
        subprocess.Popen(
            [sys.executable, os.path.join(BASE, "worker_runner.py"),
             sid, mode, str(keep_subject), json.dumps(images), source_text,
             tripo_key, llm_key, llm_base, llm_model],
            stdout=log_f, stderr=subprocess.STDOUT,
        )
    except Exception as e:
        return jsonify({"error": "无法启动生成任务: " + str(e)}), 500
    # 写入“处理中”标记，供轮询接口识别（结果文件就绪后由子进程覆盖）
    try:
        json.dump({"status": "processing"}, open(result_path, "w"), ensure_ascii=False)
    except Exception:
        pass
    return jsonify({"success": True, "status": "processing", "message": "已提交重建任务"})

@app.route("/api/reconstruct_status")
def api_reconstruct_status():
    sid = request.args.get("session_id")
    if not sid:
        return jsonify({"status": "error", "error": "缺少 session_id"}), 400
    # 优先从结果文件读取（跨进程/跨重启持久）
    result_path = os.path.join(OUTPUT, sid + "_job.json")
    if os.path.exists(result_path):
        try:
            return jsonify(json.load(open(result_path, encoding="utf-8")))
        except Exception:
            pass
    # 兼容内存态
    job = JOBS.get(sid)
    if job:
        return jsonify(job)
    # 诊断信息：带上子进程日志尾部，帮助定位“任务不存在”的真实原因
    tail = ""
    log_path = os.path.join(OUTPUT, sid + "_worker.log")
    if os.path.exists(log_path):
        try:
            tail = open(log_path, encoding="utf-8", errors="replace").read()[-300:]
        except Exception:
            pass
    return jsonify({"status": "error", "boot_time": BOOT_TIME, "boot_count": BOOT_COUNT,
        "error": "任务不存在（服务可能已重启），请重新上传并重建",
        "worker_log": tail}), 404

@app.route("/api/tune", methods=["POST"])
def api_tune():
    import mesh_ops
    data = request.get_json(force=True)
    sid = data.get("session_id")
    glb_path = os.path.join(OUTPUT, sid + ".glb") if sid else None
    if not glb_path or not os.path.exists(glb_path):
        return jsonify({"error": "请先完成重建"}), 404
    m = mesh_ops.load_mesh(glb_path)
    repair_report = None
    if data.get("repair"):
        m, repair_report = mesh_ops.repair(m, return_report=True)
    ratio = data.get("simplify_ratio")
    if ratio:
        m = mesh_ops.simplify(m, float(ratio))
    base = data.get("add_base")
    if base:
        m = mesh_ops.add_base(m, base)
    height = data.get("target_height_mm")
    if height:
        m = mesh_ops.scale_to_height(m, float(height))
    out_glb = os.path.join(OUTPUT, sid + ".glb")
    m.export(out_glb)
    chk = mesh_ops.print_check(m, float(height) if height else None)
    return jsonify({"success": True, "model_url": "/api/model/" + sid, "print_check": chk, "repair_report": repair_report})

@app.route("/api/repair", methods=["POST"])
def api_repair():
    import mesh_ops
    data = request.get_json(force=True)
    sid = data.get("session_id")
    glb_path = os.path.join(OUTPUT, sid + ".glb") if sid else None
    if not glb_path or not os.path.exists(glb_path):
        return jsonify({"error": "请先完成重建"}), 404
    m = mesh_ops.load_mesh(glb_path)
    m, report = mesh_ops.repair(m, return_report=True)
    m.export(glb_path)
    chk = mesh_ops.print_check(m)
    return jsonify({"success": True, "model_url": "/api/model/" + sid, "print_check": chk, "repair_report": report})


@app.route("/api/status")
def api_status():
    import os as _os
    return jsonify({"version": APP_VERSION, "boot_time": BOOT_TIME, "boot_count": BOOT_COUNT,
        "tripo_key_configured": bool(_os.environ.get("TRIPO_API_KEY")),
        "deepseek_key_configured": bool(_os.environ.get("DEEPSEEK_API_KEY"))})

@app.route("/api/worker_log")
def api_worker_log():
    # 诊断用：读取某次生成任务的子进程日志与结果文件，便于定位真实报错（如 Tripo 多图接口拒绝）。
    sid = request.args.get("session_id")
    if not sid:
        return jsonify({"error": "缺少 session_id"}), 400
    log_path = os.path.join(OUTPUT, sid + "_worker.log")
    job_path = os.path.join(OUTPUT, sid + "_job.json")
    log = open(log_path, encoding="utf-8", errors="replace").read() if os.path.exists(log_path) else ""
    job = None
    if os.path.exists(job_path):
        try:
            job = json.load(open(job_path, encoding="utf-8"))
        except Exception:
            pass
    return jsonify({"worker_log": log, "job": job, "boot_time": BOOT_TIME, "boot_count": BOOT_COUNT})


@app.route("/api/rawimg/<path:relpath>")
def api_rawimg(relpath):
    full = os.path.join(UPLOAD, relpath)
    if os.path.exists(full):
        return send_file(full)
    return jsonify({"error": "image not found"}), 404

@app.route("/api/model/<sid>")
def api_model(sid):
    glb_path = os.path.join(OUTPUT, sid + ".glb")
    if os.path.exists(glb_path):
        return send_file(glb_path, mimetype="model/gltf-binary")
    return jsonify({"error": "模型不存在"}), 404

@app.route("/api/export", methods=["POST"])
def api_export():
    import mesh_ops
    data = request.get_json(force=True)
    sid = data.get("session_id")
    glb_path = os.path.join(OUTPUT, sid + ".glb") if sid else None
    if not glb_path or not os.path.exists(glb_path):
        return jsonify({"error": "请先完成重建"}), 404
    m = mesh_ops.load_mesh(glb_path)
    stl_path = os.path.join(OUTPUT, sid + ".stl")
    mesh_ops.export_stl(m, stl_path)
    return jsonify({"success": True, "stl_url": "/api/download/" + sid})

@app.route("/api/download/<sid>")
def api_download(sid):
    stl_path = os.path.join(OUTPUT, sid + ".stl")
    if os.path.exists(stl_path):
        return send_file(stl_path, as_attachment=True, download_name="cinesculpt.stl")
    return jsonify({"error": "STL 不存在"}), 404

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    print("=== CineSculpt backend ===")
    print("open: http://localhost:%d" % port)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
