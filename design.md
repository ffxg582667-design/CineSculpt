# CineSculpt 设计文档

## 总体架构

三层结构：前端（HTML + Three.js）、后端（Flask）、网格处理（Trimesh）。前端负责上传与 3D 预览，后端负责重建调度与网格操作。

## 技术栈选型

| 层 | 技术 | 说明 |
| --- | --- | --- |
| 前端 | HTML + Three.js（CDN 引入） | 无需构建，浏览器直接渲染 3D |
| 后端 | Python + Flask | 提供 REST API |
| 网格处理 | Trimesh | 简化、加底座、水密性检测、导出 STL |
| 抠图 | rembg | 主角模式下去背景，保留主体 |
| 3D 重建 | 可插拔接口：占位模型 / Meshy / Tripo3D | 默认占位，可切云 API |

## 目录结构

- backend/app.py：Flask 主服务，路由入口
- backend/reconstruct.py：3D 重建可插拔接口（占位 + 云 API）
- backend/mesh_ops.py：网格操作（加底座、缩放、简化、补洞、打印性检测）
- backend/segment.py：rembg 抠图
- frontend/index.html：页面结构
- frontend/style.css：样式
- frontend/app.js：Three.js 预览与交互
- models/：预生成的 fallback 模型（.glb/.obj）
- uploads/：用户上传的图片
- output/：生成的模型和 STL

## API 接口设计

### POST /api/upload
上传 1-5 张图片。返回 session_id 和图片列表。

### POST /api/reconstruct
入参：session_id、mode（scene 场景模式 / hero 主角模式）、keep_subject（是否只保留主体）。
流程：主角模式先用 rembg 抠主体，再调用重建接口生成模型，返回模型 url。重建失败时回退到 fallback 占位模型并在返回中标记 fallback=true。

### POST /api/tune
入参：session_id 和微调项：add_base（加底座类型）、target_height_mm（目标高度）、simplify_ratio（简化比例）、repair（是否补洞）。
返回：处理后的模型 url 和打印性检测结果。

### GET /api/model/session_id
返回当前模型文件（.glb）供 Three.js 加载。

### POST /api/export
入参：session_id。用 Trimesh 导出 STL，返回下载链接。

### GET /api/print_check/session_id
返回打印性检测：最小特征尺寸估算、是否小于 0.5mm、当前尺寸、是否超过 200mm 上限。

## 3D 重建可插拔接口设计

定义统一函数 reconstruct(images, mode)，内部按优先级尝试：
1. 若配置了环境变量 MESHY_API_KEY，调用 Meshy API。
2. 若配置了 TRIPO_API_KEY，调用 Tripo3D API。
3. 否则或调用失败，返回 models 目录下的预生成占位模型。

返回统一结构：模型文件路径 + 来源标记（real 或 fallback）。这样无论现场网络或 GPU 情况如何，链路都不中断，接上 Key 即为真实重建。

## 打印性检测算法

1. 用 Trimesh 计算模型包围盒尺寸。
2. 采样网格边长，取较小百分位作为最小特征近似。
3. 换算到目标物理尺寸：最小特征物理值 = 最小特征比例 乘以 目标高度。
4. 若最小特征物理值小于 0.5mm，提示细节可能丢失，建议放大或切主角模式。
5. 若任一维度超过 200mm，提示超出打印尺寸上限。

## 网格微调 mesh_ops

- 加底座：在模型底部生成圆柱或方盒并与模型布尔合并。
- 尺寸调整：按目标高度等比缩放全模型。
- 网格简化：用 Trimesh 减少面片数量，方便打印。
- 一键修复：填补空洞、修正法线、合并重复顶点，尽量保证水密。

## 演示与 fallback 策略

- 预生成 2-3 个模型放入 models 目录，重建失败时无缝切换。
- 一键启动脚本 + Cloudflare 公网隧道，生成可分享的公网地址用于路演。

## 非目标

见 requirements.md。彩色切片、真实打印机固件对接、剧情识别均不在本次范围。
