# -*- coding: utf-8 -*-
# CineSculpt backend main service
import os
import uuid
import json
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
import reconstruct
import mesh_ops
import segment
import describe

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

def allowed(fn):
    return "." in fn and fn.rsplit(".", 1)[1].lower() in ALLOWED

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
    tripo_key = (data.get("tripo_key") or "").strip() or None
    llm_key = (data.get("llm_key") or data.get("deepseek_key") or "").strip() or None
    llm_base = (data.get("llm_base") or "").strip() or None
    llm_model = (data.get("llm_model") or "").strip() or None
    if sid not in SESSIONS:
        return jsonify({"error": "会话不存在，请重新上传"}), 404
    # NEW: image is always primary. source_text is auxiliary -> only an "AI understanding" note.
    ai_note = ""
    if source_text:
        try:
            ai_note, _ = describe.build_prompt(source_text, api_key=llm_key, base_url=llm_base, model=llm_model)
        except Exception as e:
            print("ai note build failed:", e)
            ai_note = ""
    images = SESSIONS[sid]["images"]
    if keep_subject:
        cut = []
        for i, img in enumerate(images):
            out = os.path.join(os.path.dirname(img), "cut_" + str(i) + ".png")
            cut.append(segment.extract_subject(img, out))
        images = cut
    try:
        # build public image urls (for Meshy) via cloudflare tunnel base url
        public_base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
        public_urls = None
        if public_base:
            public_urls = []
            for img in images:
                rel = os.path.relpath(img, UPLOAD).replace(os.sep, "/")
                public_urls.append(public_base + "/api/rawimg/" + rel)
        model_path, source = reconstruct.reconstruct(images, mode=mode, public_image_urls=public_urls, api_key=tripo_key)
        out_glb = os.path.join(OUTPUT, sid + ".glb")
        m = mesh_ops.load_mesh(model_path)
        m = mesh_ops.normalize_size(m)
        m.export(out_glb)
        SESSIONS[sid]["model"] = out_glb
        chk = mesh_ops.print_check(m)
        msg = "重建完成" if source == "real" else "已用占位模型演示（未配置重建 API）"
        return jsonify({"success": True, "session_id": sid, "model_url": "/api/model/" + sid, "source": source, "print_check": chk, "message": msg, "ai_note": ai_note})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/tune", methods=["POST"])
def api_tune():
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
    return jsonify({"tripo_key_configured": bool(_os.environ.get("TRIPO_API_KEY")), "deepseek_key_configured": bool(_os.environ.get("DEEPSEEK_API_KEY"))})


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
