# -*- coding: utf-8 -*-
# 3D reconstruction pluggable interface: Tripo3D (real) / local placeholder (fallback)
import os
import uuid
import asyncio
# trimesh 改为惰性导入（仅占位模型需要），缩短子进程启动时的内存峰值

MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "models")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output")
os.makedirs(MODELS_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

def _make_placeholder_model():
    import trimesh
    sphere = trimesh.creation.icosphere(subdivisions=3, radius=1.0)
    box = trimesh.creation.box(extents=(1.2, 1.2, 0.4))
    box.apply_translation((0, 0, -1.0))
    return trimesh.util.concatenate([sphere, box])

def get_fallback_model_path():
    path = os.path.join(MODELS_DIR, "placeholder.glb")
    if not os.path.exists(path):
        _make_placeholder_model().export(path)
    return path

def reconstruct(image_paths, mode="hero", public_image_urls=None, api_key=None):
    # priority: user-provided key -> server env key -> fallback placeholder
    tripo_key = api_key or os.environ.get("TRIPO_API_KEY")
    if tripo_key:
        try:
            model_path, note = _reconstruct_tripo(image_paths, tripo_key)
            return model_path, "real", ("重建完成" + note)
        except Exception as e:
            # Key 失效/额度耗尽/网络异常时优雅降级为占位模型，保证演示流程不中断
            print("Tripo 真实生成失败，降级为占位模型:", repr(e), flush=True)
            return get_fallback_model_path(), "fallback", "重建 API 调用失败（" + str(e)[:500] + "），已降级为占位模型演示"
    return get_fallback_model_path(), "fallback", "未配置重建 API（TRIPO_API_KEY），已用占位模型演示"

def _reconstruct_tripo(image_paths, api_key):
    # use official Tripo3D SDK. returns (model_path, note).
    return asyncio.run(_tripo_async(image_paths, api_key))

async def _tripo_async(image_paths, api_key):
    from tripo3d import TripoClient, TaskStatus
    async with TripoClient(api_key=api_key) as client:
        imgs = [p for p in image_paths if os.path.exists(p)]
        if not imgs:
            raise Exception("no valid image")
        note = ""
        # 多图（>=2 张）优先走 multiview_to_model 融合各角度；单图才用 image_to_model。
        # 之前只用 imgs[0]，导致模型只含第一张图内容（只有半边）。
        if len(imgs) >= 2:
            try:
                # 官方 API 要求：multiview 的 files 必须恰好 4 个槽位，顺序 [front, left, back, right]，
                # 每个槽位为 {"type":"jpg","file_token":...}，不用的视角用空对象 {} 占位，front 不能空。
                # SDK 的 multiview_to_model 只会原样拼 images 数组（不足 4 个必报 [1004] 参数无效），
                # 因此这里绕开它，手工按官方格式构造。
                files = [{}, {}, {}, {}]
                for i, p in enumerate(imgs[:4]):
                    tok = await client._image_to_file_content(p)
                    if tok:
                        files[i] = tok
                task_id = await client.create_task({"type": "multiview_to_model", "files": files})
            except Exception as e:
                # 多图融合失败（常见于账号等级 / 图片视角 / 数量限制），退回单图重建首图，
                # 保证仍能产出真实模型，并在 note 中记录真实原因便于排查。
                print("multiview_to_model failed, fallback to single image:", repr(e), flush=True)
                note = "（多图融合失败：" + str(e)[:200] + "，已用首图单图重建）"
                task_id = await client.image_to_model(image=imgs[0])
        else:
            task_id = await client.image_to_model(image=imgs[0])
        task = await client.wait_for_task(task_id, polling_interval=3.0, timeout=300, verbose=True)
        if task.status != TaskStatus.SUCCESS:
            raise Exception("tripo task not success: " + str(task.status))
        out_dir = os.path.join(OUTPUT_DIR, "tripo_" + uuid.uuid4().hex)
        os.makedirs(out_dir, exist_ok=True)
        files = await client.download_task_models(task, out_dir)
        # pick glb if available, else first file
        model_path = None
        for k, v in files.items():
            if v and str(v).lower().endswith(".glb"):
                model_path = v; break
        if not model_path:
            for k, v in files.items():
                if v:
                    model_path = v; break
        if not model_path:
            raise Exception("no model file downloaded")
        return model_path, note

def reconstruct_from_text(prompt, api_key=None):
    # text-to-3D via Tripo. returns (model_path, source).
    key = api_key or os.environ.get("TRIPO_API_KEY")
    if not key:
        return get_fallback_model_path(), "fallback"
    try:
        return asyncio.run(_tripo_text_async(prompt, key)), "real"
    except Exception as e:
        print("Tripo text-to-3d failed, fallback:", e)
        return get_fallback_model_path(), "fallback"

async def _tripo_text_async(prompt, api_key):
    from tripo3d import TripoClient, TaskStatus
    async with TripoClient(api_key=api_key) as client:
        task_id = await client.text_to_model(prompt=prompt)
        task = await client.wait_for_task(task_id, polling_interval=3.0, timeout=300, verbose=True)
        if task.status != TaskStatus.SUCCESS:
            raise Exception("tripo text task not success: " + str(task.status))
        out_dir = os.path.join(OUTPUT_DIR, "tripo_" + uuid.uuid4().hex)
        os.makedirs(out_dir, exist_ok=True)
        files = await client.download_task_models(task, out_dir)
        model_path = None
        for k, v in files.items():
            if v and str(v).lower().endswith(".glb"):
                model_path = v; break
        if not model_path:
            for k, v in files.items():
                if v:
                    model_path = v; break
        if not model_path:
            raise Exception("no model file downloaded")
        return model_path
