# -*- coding: utf-8 -*-
# 独立子进程：执行耗内存/耗时的 3D 生成任务。
# 与主 Web 进程解耦，即使本进程因 OOM 被系统杀掉，Web 服务也绝不宕机。
import sys, os, json, traceback, shutil
# 必须在 numpy/trimesh 导入前设置：限制 BLAS/OpenMP 线程栈，显著降低内存与线程开销
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# 仅保留生成必需的 reconstruct；segment/describe/mesh_ops 全部按需惰性导入，
# 避免在生成子进程里加载 trimesh（~120MB），防止 512MB 内存超限。
import reconstruct

MAX_IMG_DIM = 1600  # 上传给 Tripo 前的最大边长，控制内存与上传体积

def _ensure_pil():
    import PIL
    return PIL

def downscale(paths):
    """用 Pillow 把过大图片等比缩到 MAX_IMG_DIM 内，返回新文件路径列表（失败时退回原图）。"""
    try:
        from PIL import Image
    except Exception as e:
        print("Pillow 未安装，跳过降采样:", e, flush=True)
        return list(paths)
    out = []
    for p in paths:
        try:
            im = Image.open(p)
            w, h = im.size
            if max(w, h) > MAX_IMG_DIM:
                im.thumbnail((MAX_IMG_DIM, MAX_IMG_DIM))
                np_ = os.path.join(os.path.dirname(p), "ds_" + os.path.basename(p))
                if np_.lower().endswith((".jpg", ".jpeg", ".bmp", ".tif", ".tiff")):
                    im = im.convert("RGB"); np_ = os.path.splitext(np_)[0] + ".png"
                im.save(np_)
                out.append(np_)
            else:
                out.append(p)
        except Exception as e:
            print("downscale failed for", p, e, flush=True)
            out.append(p)
    return out

def main():
    sid        = sys.argv[1]
    mode       = sys.argv[2]
    keep_subject = (sys.argv[3].lower() == "true")
    image_paths  = json.loads(sys.argv[4])
    source_text   = sys.argv[5]
    # 用户在前端填写的密钥（来自 /api/reconstruct 透传）。空串时 reconstruct/describe 内部自动回退到服务器环境变量。
    tripo_key = sys.argv[6] if len(sys.argv) > 6 else ""
    llm_key   = sys.argv[7] if len(sys.argv) > 7 else ""
    llm_base  = sys.argv[8] if len(sys.argv) > 8 else ""
    llm_model = sys.argv[9] if len(sys.argv) > 9 else ""
    OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output")
    result_path = os.path.join(OUT, sid + "_job.json")

    def write(status, **kw):
        json.dump({"status": status, **kw}, open(result_path, "w"), ensure_ascii=False)

    try:
        # AI 理解备注（失败不影响主流程）；describe 按需惰性导入
        ai_note = ""
        if source_text:
            try:
                import describe
                ai_note, _ = describe.build_prompt(source_text,
                    api_key=llm_key or os.environ.get("DEEPSEEK_API_KEY"),
                    base_url=llm_base or None, model=llm_model or None)
            except Exception as e:
                print("ai note build failed:", e, flush=True)
                ai_note = ""

        imgs = downscale(image_paths)
        if keep_subject:
            try:
                import segment
                cut = []
                for i, img in enumerate(imgs):
                    out = os.path.join(os.path.dirname(img), "cut_%d.png" % i)
                    cut.append(segment.extract_subject(img, out))  # rembg 未装时自动退回原图
                imgs = cut
            except Exception as e:
                print("segment failed, use original:", e, flush=True)

        # Tripo 已直接产出 GLB，直接作为结果文件，跳过本地 trimesh 后处理以节省内存。
        model_path, source, fallback_reason = reconstruct.reconstruct(
            imgs, mode=mode, public_image_urls=None,
            api_key=tripo_key or os.environ.get("TRIPO_API_KEY"))
        out_glb = os.path.join(OUT, sid + ".glb")
        if os.path.abspath(model_path) != os.path.abspath(out_glb):
            shutil.copy(model_path, out_glb)
        msg = "重建完成" if source == "real" else fallback_reason
        # 生成阶段不计算 print_check（需要 trimesh）；用户点击『修理/微调』后在 Web 进程里再算。
        write("done", result={"success": True, "session_id": sid,
            "model_url": "/api/model/" + sid, "source": source,
            "print_check": None, "message": msg, "ai_note": ai_note})
    except Exception as e:
        traceback.print_exc()
        write("error", error=str(e))

if __name__ == "__main__":
    main()
