// Avisos descartados ("no me gustó"): se ocultan de la lista para que cada
// día quede solo lo que todavía vale la pena mirar. El sitio es estático
// (sin backend), así que la lista vive en localStorage del navegador: es por
// dispositivo y por perfil (cada página pasa su propia clave), y no viaja al
// repo. La clave de cada aviso es `portal:portal_id`, estable entre snapshots.

function crearDescartados(storageKey) {
  let items = {};
  try {
    items = JSON.parse(localStorage.getItem(storageKey)) || {};
  } catch {
    items = {};
  }

  const guardar = () => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(items));
    } catch {
      // Navegador sin almacenamiento (modo privado estricto): el descarte
      // dura hasta recargar la página, que es lo mejor que se puede hacer.
    }
  };

  return {
    tiene: (clave) => Object.prototype.hasOwnProperty.call(items, clave),
    agregar(clave) {
      items[clave] = { fecha: new Date().toISOString().slice(0, 10) };
      guardar();
    },
    quitar(clave) {
      delete items[clave];
      guardar();
    },
    cantidad: () => Object.keys(items).length,
  };
}

// Aviso flotante con "Deshacer", para recuperar un descarte hecho sin querer
// (sobre todo en el celular) sin tener que ir a buscarlo a la lista de descartados.
let toastTimer = null;
function mostrarToastDeshacer(texto, onDeshacer) {
  let toast = document.getElementById("descarte-toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "descarte-toast";
    toast.className = "descarte-toast";
    toast.setAttribute("role", "status");
    document.body.appendChild(toast);
  }
  toast.innerHTML = `<span></span><button type="button">Deshacer</button>`;
  toast.querySelector("span").textContent = texto;
  toast.querySelector("button").addEventListener("click", () => {
    toast.hidden = true;
    onDeshacer();
  });
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (toast.hidden = true), 6000);
}
