# -*- coding: utf-8 -*-
# 独立子进程：执行耗内存/耗时的 3D 生成任务。
# 与主 Web 进程解耦，即使本进程因 OOM 被系统杀掉，Web 服务也绝不宕机。
import sys, os, json, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reconstruct, mesh_ops, segment, describe

def main():
    sid        = sys.argv[1]
    mode       = sys.argv[2]
    keep_subject = (sys.argv[3].lower() == "true")
    image_paths  = json.loads(sys.argv[4])
    source_text   = sys.argv[5]
    OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output")
    result_path = os.path.join(OUT, sid + "_job.json")

    def write(status, **kw):
        json.dump({"status": status, **kw}, open(result_path, "w"), ensure_ascii=False)

    try:
        # AI 理解备注（失败不影响主流程）
        ai_note = ""
        if source_text:
            try:
                ai_note, _ = describe.build_prompt(source_text,
                    api_key=os.environ.get("DEEPSEEK_API_KEY"))
            except Exception as e:
                print("ai note build failed:", e, flush=True)
                ai_note = ""
        imgs = image_paths
        if keep_subject:
            cut = []
            for i, img in enumerate(imgs):
                out = os.path.join(os.path.dirname(img), "cut_%d.png" % i)
                cut.append(segment.extract_subject(img, out))  # rembg 未装时自动退回原图
            imgs = cut
        model_path, source, fallback_reason = reconstruct.reconstruct(
            imgs, mode=mode, public_image_urls=None,
            api_key=os.environ.get("TRIPO_API_KEY"))
        out_glb = os.path.join(OUT, sid + ".glb")
        m = mesh_ops.load_mesh(model_path)
        m = mesh_ops.normalize_size(m)
        m.export(out_glb)
        chk = mesh_ops.print_check(m)
        msg = "重建完成" if source == "real" else fallback_reason
        write("done", result={"success": True, "session_id": sid,
            "model_url": "/api/model/" + sid, "source": source,
            "print_check": chk, "message": msg, "ai_note": ai_note})
    except Exception as e:
        traceback.print_exc()
        write("error", error=str(e))

if __name__ == "__main__":
    main()
