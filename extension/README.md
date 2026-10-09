# RPA Step Recorder — Extensión para Chrome / Edge

Graba lo que haces en el navegador y genera la documentación del proceso en
**Word** y **PDF**. Funciona en Windows, macOS y Linux, sin instalar nada más
y **sin conexión**: todo ocurre dentro de tu navegador.

## Qué es

Una extensión Manifest V3 que registra automáticamente tu interacción con las
páginas web (clics, lo que escribes en los campos, lo que eliges en las listas,
teclas Enter y Escape). En cada paso:

- captura la pantalla,
- resalta en rojo el elemento con el que interactúas,
- escribe una descripción automática editable,
- guarda los datos técnicos para RPA (selector CSS, XPath, `id`, URL).

Las contraseñas nunca se guardan: el paso dice "Escribir la contraseña" y no
registra el contenido.

## Instalación (una sola vez, ~30 segundos)

La extensión se carga **descomprimida** en modo desarrollador. No necesita
compilarse ni empaquetarse.

1. Clona o descarga este repositorio en una carpeta que vaya a **quedarse fija**.
   No la borres ni la muevas después: el navegador la lee de ahí cada vez.
2. Abre el navegador y escribe en la barra de direcciones:
   - Chrome: `chrome://extensions`
   - Edge: `edge://extensions`
3. Activa el interruptor **"Modo de desarrollador"** (arriba a la derecha).
4. Pulsa **"Cargar descomprimida"** y selecciona la carpeta `extension/`
   (la que contiene `manifest.json`).
5. Aparecerá el icono en la barra del navegador. Si no lo ves, pulsa el icono
   de la pieza de puzle y fija **"RPA Step Recorder"**.

> El navegador avisa de las extensiones en modo desarrollador. Es normal con
> las extensiones cargadas a mano; puedes cerrar el aviso y seguir usándola.

## Cómo usarla

1. Pulsa el icono, escribe el nombre del proceso y pulsa **"Iniciar grabación"**.
2. Trabaja con normalidad. La extensión registra sola cada paso, captura la
   pantalla y muestra una tarjeta con la descripción ya escrita.
   - `Enter` → guarda el paso.
   - `Esc` → acepta la descripción sugerida tal cual.
   - 🗑️ Papelera → descarta esa captura.
   - Si no escribes nada y sigues haciendo clic, cada paso se guarda igual con
     su descripción automática. Puedes grabar de corrido y corregir después.
   - Pulsa **"Pausar"** para hacer algo que no es parte del proceso.
3. Al acabar, pulsa **"Detener y revisar"**. Se abre una página donde puedes
   corregir descripciones, reordenar o borrar pasos. El índice de la izquierda
   permite saltar de un paso a otro.
4. Pulsa **"Word"** o **"PDF"**. El documento se descarga a tu carpeta de
   descargas.

## Atajos de teclado

| Atajo (Windows / Linux) | Atajo (macOS) | Acción |
|---|---|---|
| `Ctrl+Shift+9` | `Cmd+Shift+9` | Iniciar / detener la grabación |
| `Ctrl+Shift+8` | `Cmd+Shift+8` | Añadir un paso de solo nota |

## Qué contiene el documento

- Portada con el proceso, el sistema, el autor y la fecha.
- Tabla resumen con todos los pasos numerados.
- Una página por paso: descripción, captura completa con el elemento resaltado,
  detalle ampliado y los datos técnicos para quien programe el bot (selector
  CSS, XPath, `id`, URL).

## Preguntas frecuentes

**¿Envía algo a internet?**
No. Las capturas y los documentos se generan dentro de tu navegador y se
guardan solo en tu equipo. La extensión no hace ninguna petición a ningún
servidor.

**¿Dónde se guardan las grabaciones?**
En el almacenamiento local del navegador, hasta que las borres desde la página
de revisión. Ocupan alrededor de 1,5 MB por paso, así que conviene borrar las
grabaciones ya exportadas.

**¿Funciona con ventanas emergentes y modales?**
Sí. Los modales de la página y las ventanas abiertas con `window.open` se
graban con normalidad. No se pueden capturar los diálogos del propio navegador
(`alert`, confirmar, elegir archivo, imprimir) porque no forman parte de la
página; el paso se guarda igual con su descripción automática.

**No funciona en una pestaña concreta.**
En las páginas internas del navegador (`chrome://`, `edge://`, la tienda de
extensiones) ninguna extensión puede actuar. Es una restricción del navegador.

**La captura sale de la pantalla siguiente.**
La foto se toma al pulsar el botón, antes de que la página cambie. En páginas
que redirigen al instante puede colarse la página destino: borra ese paso en la
página de revisión y repítelo.

**No puedo activar el modo de desarrollador.**
Tu empresa lo tiene bloqueado por política de Chrome. Habla con tu área de
sistemas: la alternativa es publicarla en la Chrome Web Store como extensión no
listada.

## ¿Y para aplicaciones de escritorio?

Si necesitas documentar programas de Windows fuera del navegador (ERPs, SAP
GUI, utilidades nativas), usa la [versión de escritorio](../desktop/README.md).
