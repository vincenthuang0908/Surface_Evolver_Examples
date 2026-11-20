import * as THREE from 'three';
import {OrbitControls} from './three/examples/jsm/controls/OrbitControls.js';

const byId = id => document.getElementById(id);
const pinSelect = byId('pin');
const status = byId('status');
const colors = {pcb: 0x32a482, pad: 0xe89b53, pin: 0xedcd72, other: 0x8298af, solder: 0x4b7391, selected: 0x6ddaff};
const views = [];
let original, comparison, assembly, comparedPin, activePin, inspectedSolid, solderSolidIndex;
let synchronizing = false;

function send(type, fields = {}) {
  window.parent.postMessage({isStreamlitMessage: true, type, ...fields}, window.location.origin);
}

function createView(container) {
  const renderer = new THREE.WebGLRenderer({antialias: true});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  container.append(renderer.domElement);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x172430);
  scene.add(new THREE.HemisphereLight(0xf5faff, 0x526072, 2.2));
  const light = new THREE.DirectionalLight(0xffffff, 2.0);
  light.position.set(3, -4, 8);
  scene.add(light);
  const camera = new THREE.PerspectiveCamera(38, 1, 0.01, 10000);
  camera.up.set(0, 0, 1);
  const controls = new OrbitControls(camera, renderer.domElement);
  const group = new THREE.Group();
  scene.add(group);
  const box = new THREE.Box3Helper(new THREE.Box3(), colors.selected);
  box.visible = false;
  scene.add(box);
  const view = {container, renderer, scene, camera, controls, group, box, meshes: [], labels: []};
  controls.addEventListener('change', () => {
    if (synchronizing) return;
    synchronizing = true;
    for (const other of views) {
      if (other === view) continue;
      other.camera.position.copy(camera.position);
      other.controls.target.copy(controls.target);
      other.controls.update();
    }
    synchronizing = false;
    draw();
  });
  new ResizeObserver(() => {
    const {clientWidth, clientHeight} = container;
    if (!clientWidth || !clientHeight) return;
    renderer.setSize(clientWidth, clientHeight);
    camera.aspect = clientWidth / clientHeight;
    camera.updateProjectionMatrix();
    draw();
  }).observe(container);
  views.push(view);
  return view;
}

function unpack(encoded, ArrayType) {
  const data = atob(encoded);
  const bytes = new Uint8Array(data.length);
  for (let i = 0; i < data.length; i++) bytes[i] = data.charCodeAt(i);
  return new ArrayType(bytes.buffer);
}

function loadMeshes(view, solids, withLabels) {
  for (const mesh of view.meshes) {
    view.group.remove(mesh);
    mesh.geometry.dispose();
    mesh.material.dispose();
  }
  for (const {button} of view.labels) button.remove();
  view.labels = [];
  view.meshes = solids.map(solid => {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(unpack(solid.positions, Float32Array), 3));
    geometry.setIndex(new THREE.BufferAttribute(unpack(solid.indices, Uint32Array), 1));
    // Keep a planar CAD face visibly flat at shared edges.
    const material = new THREE.MeshStandardMaterial({
      color: colors[solid.role], side: THREE.DoubleSide, roughness: 0.76, flatShading: true,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.userData = solid;
    view.group.add(mesh);
    if (withLabels && solid.role === 'pin') {
      const bounds = boxFrom(solid.bounds_mm);
      const anchor = bounds.getCenter(new THREE.Vector3());
      anchor.z = bounds.max.z + 0.22;
      for (const index of solid.pin_indices) {
        const button = document.createElement('button');
        button.className = 'pin-label';
        button.type = 'button';
        button.textContent = String(index);
        button.setAttribute('aria-label', `Inspect pin ${index}`);
        button.addEventListener('click', () => select(index, solid.index));
        view.container.append(button);
        view.labels.push({button, anchor, index});
      }
    }
    return mesh;
  });
}

function boxFrom(values) {
  return new THREE.Box3(new THREE.Vector3(...values.slice(0, 3)), new THREE.Vector3(...values.slice(3)));
}

function fit(box) {
  const center = box.getCenter(new THREE.Vector3());
  const radius = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 0.1);
  const direction = new THREE.Vector3(0.45, -0.75, 1.2).normalize();
  const visible = views.filter(view => !view.container.hidden);
  const aspect = Math.min(...visible.map(view => view.container.clientWidth / view.container.clientHeight));
  const halfFov = THREE.MathUtils.degToRad(original.camera.fov / 2);
  const distance = radius / Math.sin(Math.min(halfFov, Math.atan(Math.tan(halfFov) * aspect))) * 1.08;
  synchronizing = true;
  for (const view of views) {
    view.controls.target.copy(center);
    view.camera.position.copy(center).addScaledVector(direction, distance);
    view.controls.update();
  }
  synchronizing = false;
  draw();
}

function focusPin() {
  const connection = assembly.connections.find(row => row.pin_index === activePin);
  if (!connection) return;
  const pin = boxFrom(assembly.solids[connection.pin_solid_index].bounds_mm);
  const pad = boxFrom(assembly.solids[connection.pad_solid_index].bounds_mm);
  pin.union(pad);
  if (comparedPin === activePin) pin.union(boxFrom(comparedBounds));
  fit(pin);
}

function focusSolderJoint() {
  const solder = assembly.solids.find(solid => solid.index === solderSolidIndex);
  if (solder) fit(boxFrom(solder.bounds_mm));
}

function updateAppearance() {
  for (const view of views) {
    view.box.visible = false;
    for (const mesh of view.meshes) {
      const {role, index, pin_indices: pins, bounds_mm: bounds} = mesh.userData;
      const solder = view === original && index === solderSolidIndex;
      const inspected = view === original && index === inspectedSolid;
      const selected = solder ? inspected : role === 'pin' && pins.includes(activePin);
      mesh.visible = solder || role !== 'other' || byId('context').checked;
      mesh.material.color.setHex(selected ? colors.selected : colors[solder ? 'solder' : role]);
      mesh.material.emissive.setHex(inspected && mesh.visible ? 0x22343d : 0x000000);
      if (selected && byId('bounds').checked) {
        view.box.box.copy(boxFrom(bounds));
        view.box.visible = true;
      }
    }
  }
  const comparing = comparedPin != null && comparedPin === activePin;
  comparison.container.hidden = !comparing;
  byId('views').classList.toggle('comparing', comparing);
  byId('focus').disabled = activePin == null;
  solderFocusButton.hidden = solderSolidIndex == null;
  pinSelect.disabled = !assembly.connections.length;
  if (activePin != null) pinSelect.value = activePin;
  status.textContent = assembly.detection_error || (comparing
    ? 'Both views share the same world coordinates. Drag either view to rotate them together.'
    : 'Drag to rotate, scroll to zoom, and right-drag to pan. Click a pin, label, or solid to inspect it.');
  if (solderSolidIndex != null) {
    status.textContent = 'Drag to rotate, scroll to zoom, and right-drag to pan. Click the blue-gray solder joint to select it.';
  }
  draw();
}

function draw() {
  for (const view of views) {
    if (view.container.hidden) continue;
    const {camera, container, renderer, scene, labels} = view;
    renderer.render(scene, camera);
    const width = container.clientWidth;
    const height = container.clientHeight;
    const occupied = [];
    const ordered = [...labels].sort((a, b) => Number(b.index === activePin) - Number(a.index === activePin));
    for (const {button, anchor, index} of ordered) {
      const p = anchor.clone().project(camera);
      const x = (p.x + 1) * width / 2;
      const y = (1 - p.y) * height / 2;
      const collision = occupied.some(([ox, oy]) => Math.abs(ox - x) < 23 && Math.abs(oy - y) < 16);
      button.hidden = !byId('labels').checked || p.z < -1 || p.z > 1
        || x < 11 || x > width - 11 || y < 12 || y > height - 12 || collision;
      if (button.hidden) continue;
      occupied.push([x, y]);
      button.style.transform = `translate(${x}px, ${y}px) translate(-50%, -100%)`;
      button.setAttribute('aria-pressed', String(index === activePin));
    }
  }
}

function select(index, solidIndex) {
  activePin = index;
  inspectedSolid = solidIndex;
  updateAppearance();
  send('streamlit:setComponentValue', {value: {pin_index: activePin, solid_index: inspectedSolid}, dataType: 'json'});
}

function enablePicking(view) {
  const canvas = view.renderer.domElement;
  let start;
  canvas.addEventListener('pointerdown', event => {
    start = event.button === 0 ? [event.clientX, event.clientY] : null;
  });
  canvas.addEventListener('pointerup', event => {
    if (!start || Math.hypot(event.clientX - start[0], event.clientY - start[1]) > 4) return;
    const rect = canvas.getBoundingClientRect();
    const pointer = new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1,
      1 - (event.clientY - rect.top) / rect.height * 2);
    const ray = new THREE.Raycaster();
    ray.setFromCamera(pointer, view.camera);
    const hit = ray.intersectObjects(view.meshes.filter(mesh => mesh.visible), false)[0];
    if (hit) {
      const solid = hit.object.userData;
      select(solid.pin_indices[0] ?? activePin, solid.index);
    } else if (solderSolidIndex != null && inspectedSolid === solderSolidIndex) {
      select(activePin, null);
    }
  });
}

let comparedBounds;
function render({original: data, extracted, selection, solder_solid_index: solderIndex}) {
  if (!original) {
    original = createView(byId('original'));
    comparison = createView(byId('extracted'));
    enablePicking(original);
  }
  const newAssembly = assembly?.source_sha256 !== data.source_sha256;
  if (newAssembly) {
    assembly = data;
    loadMeshes(original, assembly.solids, true);
    pinSelect.replaceChildren(...assembly.connections.map(row => new Option(`Pin #${row.pin_index}`, row.pin_index)));
  }
  activePin = selection.pin_index;
  inspectedSolid = selection.solid_index;
  solderSolidIndex = solderIndex;
  const nextPin = extracted?.pin_index;
  const nextComparison = nextPin !== comparedPin;
  if (nextComparison) {
    comparedPin = nextPin;
    comparedBounds = extracted?.bounds_mm;
    loadMeshes(comparison, extracted?.solids ?? [], false);
  }
  updateAppearance();
  if (extracted && nextComparison) focusPin();
  else if (newAssembly) fit(boxFrom(assembly.bounds_mm));
}

pinSelect.addEventListener('change', () => {
  const index = Number(pinSelect.value);
  select(index, assembly.connections.find(row => row.pin_index === index).pin_solid_index);
});
byId('assembly').addEventListener('click', () => fit(boxFrom(assembly.bounds_mm)));
byId('focus').addEventListener('click', focusPin);
const solderFocusButton = document.createElement('button');
solderFocusButton.type = 'button';
solderFocusButton.textContent = 'Focus solder joint';
solderFocusButton.hidden = true;
solderFocusButton.addEventListener('click', focusSolderJoint);
byId('focus').after(solderFocusButton);
for (const id of ['labels', 'context', 'bounds']) byId(id).addEventListener('change', updateAppearance);

const reportHeight = () => send('streamlit:setFrameHeight', {height: document.body.offsetHeight});
new ResizeObserver(reportHeight).observe(document.body);
window.addEventListener('message', event => {
  if (event.source !== window.parent || event.origin !== window.location.origin || event.data.type !== 'streamlit:render') return;
  try {
    render(event.data.args);
  } catch (error) {
    status.textContent = `The 3D viewer could not render. Check that WebGL 2 is enabled. ${error.message}`;
    console.error(error);
  }
  reportHeight();
});
send('streamlit:componentReady', {apiVersion: 1});
reportHeight();
