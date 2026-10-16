const $ = (id) => document.getElementById(id);

let pc = null;    // la conexión WebRTC con el servidor
let ws = null;    // el WebSocket de señalización
let local = null; // mi cámara y micrófono

$("unirse").onclick = unirse;
$("colgar").onclick = colgar;

async function unirse() {
  const nombre = $("nombre").value.trim() || "Anónimo";
  $("unirse").disabled = true;
  estado("Pidiendo cámara y micrófono…");

  // 1. Mi cámara y micrófono
  local = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
  $("local").srcObject = local;

  // 2. La conexión WebRTC: envío mis pistas y preparo dónde recibir las del otro
  pc = new RTCPeerConnection({ iceServers: [{ urls: "stun:stun.l.google.com:19302" }] });
  local.getTracks().forEach((pista) => pc.addTrack(pista, local));

  const remoto = new MediaStream();
  $("remoto").srcObject = remoto;
  pc.ontrack = (e) => remoto.addTrack(e.track);

  // 3. Creo mi oferta y espero a conocer mis "direcciones" (candidatos ICE)
  await pc.setLocalDescription(await pc.createOffer());
  await esperarCandidatos(pc);

  // 4. Señalización: mando la oferta al servidor por WebSocket
  const protocolo = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${protocolo}://${location.host}/ws`);

  ws.onopen = () => {
    ws.send(JSON.stringify({ tipo: "oferta", nombre, sdp: pc.localDescription.sdp }));
    estado("Conectando…");
  };

  ws.onmessage = async (evento) => {
    const msg = JSON.parse(evento.data);

    if (msg.tipo === "respuesta") {
      await pc.setRemoteDescription({ type: "answer", sdp: msg.sdp });
      $("colgar").disabled = false;
      estado("En la sala. Esperando a la otra persona…");
    } else if (msg.tipo === "entro") {
      $("caja-remoto").classList.remove("esperando");
      $("nombre-remoto").textContent = msg.nombre;
      estado(`En llamada con ${msg.nombre}`);
    } else if (msg.tipo === "salio") {
      $("caja-remoto").classList.add("esperando");
      $("nombre-remoto").textContent = "Esperando a la otra persona…";
      estado(`${msg.nombre} salió de la llamada`);
    } else if (msg.tipo === "llena") {
      estado("La sala está llena (máximo 2 personas).");
      colgar();
    }
  };
}

function colgar() {
  if (pc) pc.close();
  if (ws) ws.close();
  if (local) local.getTracks().forEach((pista) => pista.stop());
  pc = ws = local = null;

  $("local").srcObject = null;
  $("remoto").srcObject = null;
  $("caja-remoto").classList.add("esperando");
  $("nombre-remoto").textContent = "Esperando a la otra persona…";
  $("unirse").disabled = false;
  $("colgar").disabled = true;
  if (!$("estado").textContent.includes("llena")) estado("Llamada terminada.");
}

// Espera a que el navegador termine de reunir candidatos ICE (máximo 3 s)
function esperarCandidatos(pc) {
  return new Promise((listo) => {
    if (pc.iceGatheringState === "complete") return listo();
    pc.addEventListener("icegatheringstatechange", () => {
      if (pc.iceGatheringState === "complete") listo();
    });
    setTimeout(listo, 3000);
  });
}

function estado(texto) {
  $("estado").textContent = texto;
}
