let canvas;
let engine;
let scene;
let camera;

let simulationData = null;
let events = [];
let eventsByJob = {};
let machinePositions = {};
let machineMeshes = {};
let jobMeshes = {};
let jobIndexMap = {};
let dynamicMeshes = [];

let isPlaying = false;
let wallStartTime = null;
let pausedSimTime = 0;
let currentSimTime = 0;
let maxSimTime = 0;

const TRANSIT_DURATION = 0.5;

const machineIdleColor = new BABYLON.Color3(0.13, 0.77, 0.37);
const machineBusyColor = new BABYLON.Color3(0.98, 0.80, 0.08);
const machineDownColor = new BABYLON.Color3(0.94, 0.27, 0.27);

const jobColors = [
    new BABYLON.Color3(0.23, 0.51, 0.96),
    new BABYLON.Color3(0.91, 0.35, 0.35),
    new BABYLON.Color3(0.60, 0.40, 0.95),
    new BABYLON.Color3(0.20, 0.80, 0.75),
    new BABYLON.Color3(0.95, 0.55, 0.20),
];


window.addEventListener("DOMContentLoaded", () => {
    initScene();
    bindUI();

    engine.runRenderLoop(() => {
        updateAnimation();
        scene.render();
    });

    window.addEventListener("resize", () => {
        engine.resize();
    });
});


function initScene() {
    canvas = document.getElementById("renderCanvas");
    engine = new BABYLON.Engine(canvas, true);

    scene = new BABYLON.Scene(engine);
    scene.clearColor = new BABYLON.Color4(0.03, 0.05, 0.10, 1.0);

    camera = new BABYLON.ArcRotateCamera(
        "camera",
        Math.PI / 2,
        Math.PI / 3,
        18,
        new BABYLON.Vector3(0, 0, 0),
        scene
    );

    camera.attachControl(canvas, true);

    const light1 = new BABYLON.HemisphericLight(
        "light1",
        new BABYLON.Vector3(0, 1, 0),
        scene
    );
    light1.intensity = 0.8;

    const light2 = new BABYLON.DirectionalLight(
        "light2",
        new BABYLON.Vector3(-1, -2, -1),
        scene
    );
    light2.position = new BABYLON.Vector3(10, 20, 10);
    light2.intensity = 0.6;

    const ground = BABYLON.MeshBuilder.CreateGround(
        "ground",
        {
            width: 28,
            height: 14
        },
        scene
    );

    const groundMat = new BABYLON.StandardMaterial("groundMat", scene);
    groundMat.diffuseColor = new BABYLON.Color3(0.12, 0.16, 0.22);
    groundMat.specularColor = new BABYLON.Color3(0, 0, 0);
    ground.material = groundMat;

    createAreaLabel("等待区", new BABYLON.Vector3(-10, 0.05, -5));
    createAreaLabel("完成区", new BABYLON.Vector3(10, 0.05, -5));
}


function bindUI() {
    document.getElementById("loadBtn").addEventListener("click", loadSimulation);
    document.getElementById("playBtn").addEventListener("click", play);
    document.getElementById("pauseBtn").addEventListener("click", pause);
    document.getElementById("resetBtn").addEventListener("click", resetPlayback);
}


async function loadSimulation() {
    const seed = Number(document.getElementById("seedInput").value || 42);

    const url = `/demo/pipeline?seed=${seed}`;

    const resp = await fetch(url);
    const data = await resp.json();

    simulationData = data;
    events = data.simulation.events || [];
    events.sort((a, b) => a.actual_start - b.actual_start);

    maxSimTime = data.simulation.actual_makespan || 0;

    document.getElementById("plannedMakespan").innerText =
        data.simulation.planned_makespan.toFixed(2);

    document.getElementById("actualMakespan").innerText =
        data.simulation.actual_makespan.toFixed(2);

    buildVisualization(data);
    resetPlayback();

    console.log("Loaded simulation:", data);
}


function buildVisualization(data) {
    clearDynamicMeshes();

    machinePositions = {};
    machineMeshes = {};
    jobMeshes = {};
    eventsByJob = {};

    const machineIds = Object.keys(data.schedule.machines)
        .map(Number)
        .sort((a, b) => a - b);

    const spacing = 6;
    const startX = -((machineIds.length - 1) * spacing) / 2;

    machineIds.forEach((machineId, index) => {
        const x = startX + index * spacing;
        const pos = new BABYLON.Vector3(x, 0.5, 0);

        machinePositions[machineId] = pos;
        machineMeshes[machineId] = createMachine(machineId, pos);
    });

    for (const e of events) {
        const jobId = e.job_id;

        if (!eventsByJob[jobId]) {
            eventsByJob[jobId] = [];
        }

        eventsByJob[jobId].push(e);
    }

    const jobIds = Object.keys(eventsByJob)
        .map(Number)
        .sort((a, b) => a - b);

    jobIds.forEach((jobId, index) => {
        jobIndexMap[jobId] = index; // 记录排名索引
        const mesh = createJob(jobId);
        jobMeshes[jobId] = mesh;
    });
}


function clearDynamicMeshes() {
    for (const mesh of dynamicMeshes) {
        mesh.dispose();
    }

    dynamicMeshes = [];
    jobIndexMap = {};
}


function createMaterial(name, color) {
    const mat = new BABYLON.StandardMaterial(name, scene);
    mat.diffuseColor = color;
    mat.specularColor = new BABYLON.Color3(0.2, 0.2, 0.2);
    return mat;
}


function createMachine(machineId, position) {
    const mesh = BABYLON.MeshBuilder.CreateBox(
        `machine_${machineId}`,
        {
            width: 2.2,
            depth: 2.2,
            height: 1.0
        },
        scene
    );

    mesh.position = position.clone();
    mesh.material = createMaterial(
        `machine_mat_${machineId}`,
        machineIdleColor
    );

    dynamicMeshes.push(mesh);

    createTextLabel(
        `机器 ${machineId}`,
        new BABYLON.Vector3(position.x, 1.4, position.z)
    );

    return mesh;
}


function createJob(jobId) {
    const mesh = BABYLON.MeshBuilder.CreateBox(
        `job_${jobId}`,
        {
            width: 0.8,
            depth: 0.8,
            height: 0.8
        },
        scene
    );

    mesh.position = getWaitingPosition(jobId);
    mesh.material = createMaterial(
        `job_mat_${jobId}`,
        jobColors[jobId % jobColors.length]
    );

    dynamicMeshes.push(mesh);

    const label = createTextLabel(
        `J${jobId}`,
        mesh.position.add(new BABYLON.Vector3(0, 0.8, 0))
    );

    mesh.metadata = {
        label
    };

    return mesh;
}


function createTextLabel(text, position) {
    const plane = BABYLON.MeshBuilder.CreatePlane(
        `label_${text}_${Math.random()}`,
        {
            width: 2.2,
            height: 0.7
        },
        scene
    );

    plane.position = position.clone();
    plane.billboardMode = BABYLON.Mesh.BILLBOARDMODE_ALL;

    const texture = new BABYLON.DynamicTexture(
        `texture_${text}_${Math.random()}`,
        {
            width: 512,
            height: 160
        },
        scene,
        false
    );

    texture.hasAlpha = true;
    texture.drawText(
        text,
        null,
        95,
        "bold 72px Arial",
        "white",
        "transparent",
        true
    );

    const mat = new BABYLON.StandardMaterial(
        `label_mat_${text}_${Math.random()}`,
        scene
    );

    mat.diffuseTexture = texture;
    mat.emissiveColor = new BABYLON.Color3(1, 1, 1);
    mat.backFaceCulling = false;

    plane.material = mat;

    dynamicMeshes.push(plane);

    return plane;
}


function createAreaLabel(text, position) {
    const plane = BABYLON.MeshBuilder.CreatePlane(
        `area_${text}`,
        {
            width: 3,
            height: 0.8
        },
        scene
    );

    plane.position = position;
    plane.rotation.x = Math.PI / 2;

    const texture = new BABYLON.DynamicTexture(
        `area_texture_${text}`,
        {
            width: 512,
            height: 160
        },
        scene,
        false
    );

    texture.hasAlpha = true;
    texture.drawText(
        text,
        null,
        100,
        "bold 64px Arial",
        "white",
        "transparent",
        true
    );

    const mat = new BABYLON.StandardMaterial(`area_mat_${text}`, scene);
    mat.diffuseTexture = texture;
    mat.emissiveColor = new BABYLON.Color3(0.8, 0.8, 0.8);
    mat.backFaceCulling = false;

    plane.material = mat;
}


function play() {
    if (!simulationData) {
        alert("请先点击 加载仿真");
        return;
    }

    if (!isPlaying) {
        isPlaying = true;
        wallStartTime = performance.now() - pausedSimTime * 1000 / getSpeed();
    }
}


function pause() {
    isPlaying = false;
    pausedSimTime = currentSimTime;
}


function resetPlayback() {
    isPlaying = false;
    wallStartTime = null;
    // 修复：初始时间设为 -0.01，确保所有 Job 满足 t < first.actual_start
    pausedSimTime = -0.01;
    currentSimTime = -0.01;

    document.getElementById("simTime").innerText = "0.00";

    if (simulationData) {
        updateMachineStates(0);
        updateJobStates(-0.01);
    }
}


function getSpeed() {
    return Number(document.getElementById("speedInput").value || 1);
}


function updateAnimation() {
    if (!simulationData) {
        return;
    }

    if (isPlaying) {
        const now = performance.now();
        const elapsedSeconds = (now - wallStartTime) / 1000.0;

        // 这里定义：speed = 1 时，1 秒现实时间 = 1 小时仿真时间
        currentSimTime = elapsedSeconds * getSpeed();

        if (currentSimTime >= maxSimTime) {
            currentSimTime = maxSimTime;
            isPlaying = false;
            pausedSimTime = currentSimTime;
        }
    } else {
        currentSimTime = pausedSimTime;
    }

    document.getElementById("simTime").innerText =
        currentSimTime.toFixed(2);

    updateMachineStates(currentSimTime);
    updateJobStates(currentSimTime);
}


function updateMachineStates(t) {
    if (!simulationData) {
        return;
    }

    const downtimeMap = simulationData.simulation.downtimes || {};

    for (const machineIdStr of Object.keys(machineMeshes)) {
        const machineId = Number(machineIdStr);
        const mesh = machineMeshes[machineId];

        const isDown = isMachineDown(machineId, t, downtimeMap);
        const isBusy = isMachineBusy(machineId, t);

        if (isDown) {
            mesh.material.diffuseColor = machineDownColor;
        } else if (isBusy) {
            mesh.material.diffuseColor = machineBusyColor;
        } else {
            mesh.material.diffuseColor = machineIdleColor;
        }
    }
}


function isMachineDown(machineId, t, downtimeMap) {
    const windows = downtimeMap[machineId] || downtimeMap[String(machineId)] || [];

    for (const w of windows) {
        if (w.start <= t && t <= w.end) {
            return true;
        }
    }

    return false;
}


function isMachineBusy(machineId, t) {
    for (const e of events) {
        if (
            e.machine_id === machineId &&
            e.actual_start <= t &&
            t <= e.actual_end
        ) {
            return true;
        }
    }

    return false;
}


function updateJobStates(t) {
    for (const jobIdStr of Object.keys(jobMeshes)) {
        const jobId = Number(jobIdStr);
        const mesh = jobMeshes[jobId];
        const jobEvents = eventsByJob[jobId] || [];

        if (jobEvents.length === 0) {
            continue;
        }

        const pos = getJobPositionAtTime(jobId, jobEvents, t);

        mesh.position.copyFrom(pos);

        if (mesh.metadata && mesh.metadata.label) {
            mesh.metadata.label.position = pos.add(new BABYLON.Vector3(0, 0.9, 0));
        }
    }
}


function getJobPositionAtTime(jobId, jobEvents, t) {
    const first = jobEvents[0];
    const last = jobEvents[jobEvents.length - 1];

    // 还没开始
    if (t < first.actual_start) {
        return getWaitingPosition(jobId);
    }

    // 已完成
    if (t >= last.actual_end) {
        return getFinishedPosition(jobId);
    }

    for (let i = 0; i < jobEvents.length; i++) {
        const e = jobEvents[i];

        const machinePos = machinePositions[e.machine_id];

        // 正在某台机器上加工
        if (e.actual_start <= t && t < e.actual_end) {
            const progress = (t - e.actual_start) / (e.actual_end - e.actual_start + 1e-9);

            // 加工时轻微上下跳动，表示正在运行
            const yOffset = 0.9 + Math.sin(progress * Math.PI * 8) * 0.08;

            return new BABYLON.Vector3(
                machinePos.x,
                yOffset,
                machinePos.z
            );
        }

        // 在两道工序之间移动
        if (i < jobEvents.length - 1) {
            const next = jobEvents[i + 1];

            if (e.actual_end < t && t < next.actual_start) {
                const from = machinePositions[e.machine_id];
                const to = machinePositions[next.machine_id];

                const ratio = (t - e.actual_end) / (next.actual_start - e.actual_end + 1e-9);

                const p = BABYLON.Vector3.Lerp(from, to, ratio);

                return new BABYLON.Vector3(
                    p.x,
                    0.9,
                    p.z + 1.8
                );
            }
        }
    }

    return getWaitingPosition(jobId);
}


function getWaitingPosition(jobId) {
    const index = jobIndexMap[jobId] !== undefined ? jobIndexMap[jobId] : jobId;
    return new BABYLON.Vector3(
        -10,
        0.6,
        -2 + index * 1.2  // 用 index 而非 jobId
    );
}


function getFinishedPosition(jobId) {
    const index = jobIndexMap[jobId] !== undefined ? jobIndexMap[jobId] : jobId;
    return new BABYLON.Vector3(
        10,
        0.6,
        -2 + index * 1.2  // 用 index 而非 jobId
    );
}
