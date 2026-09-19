import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

let sessionId = null;
let reconstructedSid = null;  // lock the session that has a built model
let mode = "hero";
let scene, camera, renderer, controls, currentMesh;
let pickedFiles = [];

const fileInput = document.getElementById("fileInput");
const uploadLabel = document.getElementById("uploadLabel");
const uploadText = document.getElementById("uploadText");
const thumbs = document.getElementById("thumbs");

fileInput.addEventListener("change", () => {
    const newFiles = Array.from(fileInput.files);
    for (const f of newFiles) {
        if (pickedFiles.length >= 5) { alert("最多 5 张"); break; }
        pickedFiles.push(f);
    }
    fileInput.value = "";
    renderThumbs();
    if (pickedFiles.length > 0) uploadSession();
});

function renderThumbs() {
    thumbs.innerHTML = "";
    pickedFiles.forEach((f, idx) => {
        const wrap = document.createElement("div");
        wrap.className = "thumb";
        const img = document.createElement("img");
        img.src = URL.createObjectURL(f);
        const del = document.createElement("span");
        del.className = "thumb-del";
        del.textContent = "x";
        del.addEventListener("click", () => { pickedFiles.splice(idx, 1); renderThumbs(); if (pickedFiles.length>0) uploadSession(); });
        wrap.appendChild(img);
        wrap.appendChild(del);
        thumbs.appendChild(wrap);
    });
    if (pickedFiles.length > 0) {
        uploadText.textContent = "已选择 " + pickedFiles.length + " 张（可继续添加）";
        uploadLabel.classList.add("has-file");
    } else {
        uploadText.textContent = "选择 4-5 张不同角度截图";
        uploadLabel.classList.remove("has-file");
    }
}

function uploadSession(cb) {
    const fd = new FormData();
    pickedFiles.forEach(f => fd.append("files", f));
    fetch("/api/upload", { method:"POST", body:fd })
        .then(r => r.json()).then(d => {
            if (d.success) { sessionId = d.session_id; if (cb) cb(); }
            else { alert(d.error); if (cb) cb(true); }
        }).catch(() => { if (cb) cb(true); });
}

document.getElementById("heroBtn").addEventListener("click", () => setMode("hero"));
document.getElementById("sceneBtn").addEventListener("click", () => setMode("scene"));
function setMode(m) {
    mode = m;
    document.getElementById("heroBtn").classList.toggle("active", m==="hero");
    document.getElementById("sceneBtn").classList.toggle("active", m==="scene");
}

document.getElementById("reconstructBtn").addEventListener("click", () => {
    if (pickedFiles.length === 0) { alert("请先上传图片"); return; }
    const btn = document.getElementById("reconstructBtn");
    const msg = document.getElementById("reconMsg");
    btn.disabled = true; msg.textContent = "正在上传图片...";
    // 每次重建前重新上传：确保会话在当前服务实例上有效，
    // 彻底避免服务器重启/重新部署导致的「会话不存在，请重新上传」。
    uploadSession(() => startReconstruct(btn, msg));
});

function startReconstruct(btn, msg) {
    msg.textContent = "任务已提交，AI 生成中（通常 1-2 分钟），请勿刷新页面...";
    fetch("/api/reconstruct", { method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({ session_id:sessionId, mode:mode, keep_subject: mode==="hero", source_text: (document.getElementById("sourceInput") ? document.getElementById("sourceInput").value : ""), tripo_key: getUserKeys().tripo_key, llm_key: getUserKeys().llm_key, llm_base: getUserKeys().llm_base, llm_model: getUserKeys().llm_model }) })
        .then(r => r.json()).then(d => {
            if (d.success) { pollReconstruct(btn, msg, 0); }
            else { btn.disabled = false; msg.textContent = "错误: " + d.error; }
        }).catch(e => { btn.disabled=false; msg.textContent="重建失败，请重试"; });
}

function pollReconstruct(btn, msg, tries) {
    if (tries > 200) { btn.disabled = false; msg.textContent = "等待超时，请重试"; return; }
    fetch("/api/reconstruct_status?session_id=" + sessionId)
        .then(r => r.json()).then(d => {
            if (d.status === "done") {
                btn.disabled = false;
                const r = d.result;
                reconstructedSid = r.session_id;
                msg.textContent = r.message + (r.ai_note ? "｜AI理解：" + r.ai_note : "");
                loadModel(r.model_url);
                showPrintCheck(r.print_check);
                document.getElementById("tuneCard").style.display = "block";
                document.getElementById("manualCard").style.display = "block";
                document.getElementById("exportCard").style.display = "block";
            } else if (d.status === "error") {
                btn.disabled = false;
                let t = "错误: " + d.error;
                if (d.worker_log) t += "｜日志: " + String(d.worker_log).slice(0, 150);
                msg.textContent = t;
            } else {
                msg.textContent = "AI 生成中... 已等待 " + (tries * 3) + " 秒（Tripo 通常 1-2 分钟）";
                setTimeout(() => pollReconstruct(btn, msg, tries + 1), 3000);
            }
        }).catch(e => { setTimeout(() => pollReconstruct(btn, msg, tries + 1), 3000); });
}

document.getElementById("simRange").addEventListener("input", e => {
    document.getElementById("simVal").textContent = Math.round(e.target.value*100) + "%";
});
document.getElementById("repairBtn").addEventListener("click", () => {
    if (!reconstructedSid) { alert("请先完成重建"); return; }
    const btn = document.getElementById("repairBtn");
    const msg = document.getElementById("repairMsg");
    btn.disabled = true; msg.textContent = "AI 正在修理（去碎片/补洞/水密），约 30-60 秒，请耐心等待...";
    fetch("/api/repair", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({session_id:reconstructedSid}) })
        .then(r => r.json()).then(d => {
            btn.disabled = false;
            if (d.success) {
                loadModel(d.model_url + "?t=" + Date.now());
                showPrintCheck(d.print_check);
                const rep = d.repair_report || {};
                msg.textContent = "修理完成：去除碎片 " + (rep.components_removed||0) + " 个，补洞 " + (rep.holes_before||0) + " 处，水密：" + (rep.watertight ? "是" : "否");
            } else { msg.textContent = "错误: " + d.error; }
        }).catch(e => { btn.disabled=false; msg.textContent="修理失败"; });
});

document.getElementById("tuneBtn").addEventListener("click", () => {
    if (!reconstructedSid) { alert("请先完成重建"); return; }
    const body = {
        session_id: reconstructedSid,
        add_base: document.getElementById("baseSel").value,
        target_height_mm: document.getElementById("heightInput").value,
        simplify_ratio: document.getElementById("simRange").value
    };
    fetch("/api/tune", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body) })
        .then(r => r.json()).then(d => {
            if (d.success) { loadModel(d.model_url + "?t=" + Date.now()); showPrintCheck(d.print_check); }
            else alert(d.error);
        });
});

document.getElementById("exportBtn").addEventListener("click", () => {
    const msg = document.getElementById("exportMsg");
    msg.textContent = "正在生成 STL...";
    fetch("/api/export", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({session_id:reconstructedSid}) })
        .then(r => r.json()).then(d => {
            if (d.success) {
                msg.textContent = "文件已生成！";
                const a = document.createElement("a");
                a.href = d.stl_url;
                a.textContent = "点击下载 STL（可发送至 MakerMuse 云打印）";
                a.style.color = "#c86cff"; a.style.marginLeft = "6px";
                msg.appendChild(a);
            } else { msg.textContent = d.error; }
        });
});

function showPrintCheck(chk) {
    if (!chk) return;
    const el = document.getElementById("printCheck");
    let html = "打印性检测：尺寸 " + chk.size_mm.join(" x ") + " mm，最小特征 " + chk.min_feature_mm + " mm。";
    if (chk.warnings && chk.warnings.length) {
        html += "<br>提示：" + chk.warnings.join("；");
        el.className = "print-check warn";
    } else {
        html += " 可正常打印。";
        el.className = "print-check ok";
    }
    el.innerHTML = html;
}

function initViewer() {
    const viewer = document.getElementById("viewer");
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x141530);
    camera = new THREE.PerspectiveCamera(45, viewer.clientWidth/viewer.clientHeight, 0.1, 1000);
    camera.position.set(3, 2, 4);
    renderer = new THREE.WebGLRenderer({ antialias:true });
    renderer.setSize(viewer.clientWidth, viewer.clientHeight);
    viewer.innerHTML = "";
    viewer.appendChild(renderer.domElement);
    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    scene.add(new THREE.AmbientLight(0xffffff, 0.6));
    const dl = new THREE.DirectionalLight(0xffffff, 0.8); dl.position.set(5,10,7); scene.add(dl);
    animate();
}
function animate() { requestAnimationFrame(animate); if (controls) controls.update(); if (renderer) renderer.render(scene, camera); }

function loadModel(url) {
    if (!scene) initViewer();
    if (currentMesh) { scene.remove(currentMesh); }
    const loader = new GLTFLoader();
    loader.load(url, (gltf) => {
        currentMesh = gltf.scene;
        const box = new THREE.Box3().setFromObject(currentMesh);
        const center = box.getCenter(new THREE.Vector3());
        currentMesh.position.sub(center);
        scene.add(currentMesh);
    }, undefined, (err) => { console.error(err); });
}


// ===== API settings (stored in browser localStorage) =====
function getUserKeys() {
    return {
        tripo_key: localStorage.getItem("cs_tripo_key") || "",
        llm_key: localStorage.getItem("cs_llm_key") || "",
        llm_base: localStorage.getItem("cs_llm_base") || "",
        llm_model: localStorage.getItem("cs_llm_model") || ""
    };
}
const settingsBtn = document.getElementById("settingsBtn");
const settingsModal = document.getElementById("settingsModal");
if (settingsBtn) {
    settingsBtn.addEventListener("click", () => {
        const k = getUserKeys();
        document.getElementById("tripoKeyInput").value = k.tripo_key;
        document.getElementById("llmKeyInput").value = k.llm_key;
        document.getElementById("llmBaseInput").value = k.llm_base;
        document.getElementById("llmModelInput").value = k.llm_model;
        document.getElementById("settingsMsg").textContent = "";
        settingsModal.style.display = "flex";
    });
    document.getElementById("closeSettingsBtn").addEventListener("click", () => {
        settingsModal.style.display = "none";
    });
    document.getElementById("saveKeysBtn").addEventListener("click", () => {
        localStorage.setItem("cs_tripo_key", document.getElementById("tripoKeyInput").value.trim());
        localStorage.setItem("cs_llm_key", document.getElementById("llmKeyInput").value.trim());
        localStorage.setItem("cs_llm_base", document.getElementById("llmBaseInput").value.trim());
        localStorage.setItem("cs_llm_model", document.getElementById("llmModelInput").value.trim());
        document.getElementById("settingsMsg").textContent = "已保存！下次重建将使用你的 Key。";
        setTimeout(() => { settingsModal.style.display = "none"; }, 900);
    });
}
