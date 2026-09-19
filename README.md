# CineSculpt · 电影场景 3D 打印

把电影里的一个瞬间，变成能拿在手上的实体摆件。

上传电影截图 → AI 抠出主体 → 生成 3D 模型 → 网页里旋转查看 → 打印前微调与可打印性检测 → 导出 STL 直接送进 3D 打印机。

在线体验（部署后填写）：`https://xxx.onrender.com`

---

## 它解决什么问题

电影带来的情绪会随时间淡掉，而市面上的周边大多是平面印刷品。CineSculpt 把「情绪」转成「可触摸的物理纪念品」：你提供截图，剩下的链路全部自动化。

产品定位是**生成 / 再创作**，不是毫米级几何复刻。AI 3D 重建本质是根据图片合理「脑补」，追求的是情绪共鸣与审美。

## 核心功能

| 功能 | 说明 |
| --- | --- |
| 多图上传 | 支持 1-5 张同场景不同角度截图（JPG/PNG/BMP/TIFF） |
| 主体提取 | rembg (u2net) 智能抠图 + alpha matting，合成白底，显著提升重建质量 |
| 3D 重建 | 调用 Tripo3D image-to-model 真实生成；未配置 Key 时自动降级为占位模型，保证流程可演示 |
| 场景理解 | 可选接入 DeepSeek，把剧情/原著描述转成「AI 理解笔记」辅助重建 |
| 3D 预览 | Three.js 在线渲染，鼠标拖拽旋转、滚轮缩放 |
| 打印前微调 | 一键补洞修复、网格简化、自动生成圆柱/方形底座、按目标高度缩放 |
| 可打印性检测 | 水密性检查、最小特征尺寸估算（< 0.5mm 会告警）、最大尺寸限制 |
| 导出 STL | 一键导出，直接送切片软件或云打印 |

## 技术栈

- **前端**：原生 HTML/CSS/JS + Three.js
- **后端**：Python Flask + Gunicorn
- **网格处理**：Trimesh / NumPy
- **AI 能力**：Tripo3D SDK（图生 3D）、rembg（抠图）、DeepSeek（语义理解）
- **部署**：Render（Procfile + Gunicorn）

## 本地运行

```bash
pip install -r requirements.txt

export TRIPO_API_KEY=你的Tripo密钥      # 可选，不填则使用占位模型演示
export DEEPSEEK_API_KEY=你的DeepSeek密钥 # 可选，仅用于场景理解

python backend/app.py
# 打开 http://localhost:5001
```

## 云端部署（Render）

1. 新建 Web Service，连接本仓库
2. Build Command：`pip install -r requirements.txt`
3. Start Command：`gunicorn --chdir backend app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 600`
4. 环境变量填 `TRIPO_API_KEY`、`DEEPSEEK_API_KEY`（均可选）

> 注：免费档 15 分钟无访问会休眠，首次打开需等待约 30-50 秒冷启动。
> 若部署时报内存不足，删除 `requirements.txt` 中的 `rembg` 一行重新部署即可，抠图功能会自动降级为「使用原图」，其余功能不受影响。

## 目录结构

```
backend/
  app.py          Flask 主服务与 API
  segment.py      主体提取（rembg）
  reconstruct.py  3D 重建可插拔接口（Tripo3D / 占位模型）
  describe.py     DeepSeek 场景理解
  mesh_ops.py     网格修复、简化、底座、缩放、打印性检测
frontend/
  index.html / style.css / app.js
```

## API

| 接口 | 方法 | 说明 |
| --- | --- | --- |
| `/api/upload` | POST | 上传图片，返回 session_id |
| `/api/reconstruct` | POST | 执行 3D 重建 |
| `/api/tune` | POST | 微调（修复/简化/底座/缩放） |
| `/api/repair` | POST | 一键补洞修复 |
| `/api/model/<sid>` | GET | 获取 GLB 模型 |
| `/api/export` | POST | 导出 STL |
| `/api/status` | GET | 检查服务端 Key 配置状态 |
