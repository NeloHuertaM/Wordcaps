# WordCaps

Subtítulos animados palabra a palabra para DaVinci Resolve (gratuito y Studio). Transcribe el audio del timeline en tu ordenador, agrupa las palabras, las maqueta en filas y crea un clip **Text+ por palabra**, con animación de entrada, resalte de la palabra que suena y palabras clave más grandes. Los clips quedan como Text+ normales y editables.

## Cómo funciona

```
 navegador (interfaz)  <-HTTP local->  app Python  <-buzón de ficheros->  script Lua dentro de Resolve
                                          |                                  (Workspace > Scripts > WordCaps)
                                     whisper.cpp
```

- **App Python** (`wordcaps/`, solo biblioteca estándar): sirve la interfaz en `http://127.0.0.1:8765`, descarga y ejecuta whisper.cpp, calcula grupos, posiciones y fotogramas clave.
- **Puente Lua** (`resolve/`): Resolve 21.1 gratuito ejecuta los scripts en un entorno sin `io`, `os.execute` ni sockets. Por eso la app deja cada petición en `request.lua` dentro de un buzón (el script la lee con `loadfile`) y el script contesta escribiendo en `Fusion.prefs` (`SetPrefs` + `SavePrefs`), que la app lee del disco.
- **Plantilla**: los clips se crean con `MediaPool:AppendToTimeline` a partir de un Text+ que tengas en el Media Pool. Así cada palabra hereda el estilo base de tu plantilla (sombra, fondo, etc.) y WordCaps solo cambia texto, fuente, tamaño, posición, colores y animación.

## Requisitos

- DaVinci Resolve 19 o posterior. El diseño sigue las restricciones de la API de 21.1, pero no se ha ejecutado contra Resolve (ver *Estado*).
- Python 3.9 o posterior.
- Windows: whisper.cpp se descarga solo la primera vez. macOS: `brew install whisper-cpp` o define `WORDCAPS_WHISPER_CLI` con la ruta a `whisper-cli`.

## Uso

1. Ejecuta `WordCaps.bat` (o `python -m wordcaps`). Se abre la interfaz en el navegador.
2. Pulsa **Instalar script**. Copia `WordCaps.lua` a la carpeta de scripts de Resolve.
3. En Resolve: **Workspace > Scripts > WordCaps** (una vez por sesión). En Studio, `Preferences > General > External scripting` en *Local*.
4. **Plantilla**: pulsa *Insertar Text+ en el timeline*, dale estilo si quieres, arrástralo al Media Pool y renómbralo a `WordCaps Word`. Pulsa *Actualizar*.
5. **Texto**: *Transcribir el timeline* (renderiza el audio y lo pasa por whisper.cpp) o *Importar SRT*. Puedes corregir palabras en la lista.
6. Ajusta maquetado, estilo y animación mirando la vista previa.
7. **Generar en Resolve**. WordCaps añade pistas de vídeo nuevas (una por posición de palabra en el grupo) y coloca los clips. *Ejecutar todo* hace transcripción y generación seguidas.

## Ajustes principales

| Ajuste | Qué hace |
| --- | --- |
| Modo | *Grupos*: las palabras aparecen una a una y se quedan hasta que acaba el grupo. *Una palabra cada vez*: una sola palabra centrada. |
| Palabras por grupo, caracteres por línea, líneas | Cuándo se corta un grupo y cómo se reparte en filas. |
| Pausa que corta grupo | Un silencio mayor empieza grupo nuevo. |
| Palabras clave | La más larga de cada grupo o tu lista: se escalan y llevan el color de resalte. |
| Animación | `pop`, `bounce`, `grow`, `punch` o ninguna, animando `Size` del Text+. |
| Ancho medio de letra | Respaldo para letras que la interfaz no mide. Los anchos reales se miden con la fuente instalada en tu sistema. |

## Variables de entorno

| Variable | Para qué |
| --- | --- |
| `WORDCAPS_DATA_DIR` | Carpeta de datos (buzón, modelos, whisper.cpp). Por defecto `%LOCALAPPDATA%\WordCaps`. Defínela si tu ruta de usuario tiene tildes o eñes: Resolve no abre desde un script rutas con caracteres fuera de ASCII. |
| `WORDCAPS_WHISPER_CLI` | Ruta a un `whisper-cli` ya instalado. |
| `WORDCAPS_RESOLVE_SUPPORT_DIR` | Carpeta de soporte de Resolve, si no está en la ruta habitual. |

## Tests

```bash
python -m unittest discover -s tests -t .
```

`tests/test_bridge_lua_e2e.py` arranca el núcleo Lua real en LuaJIT dentro de Docker contra un Resolve simulado y le habla por el buzón; se salta si no hay Docker. Los tests del núcleo Lua solo:

```bash
docker run --rm -v "$PWD:/src:ro" alpine:3.20 sh -c "apk add --no-cache luajit >/dev/null && luajit /src/tests/lua/test_core.lua"
```

## Estado

Probado: maquetado, animaciones, SRT, lectura de la salida de whisper, descargas, el núcleo Lua en LuaJIT contra un Resolve simulado, el protocolo del puente de punta a punta (la app Python hablando con ese Lua real) y la interfaz.

**Sin probar contra un Resolve real.** El Resolve simulado escribe `Fusion.prefs` con la forma que la app espera, así que el test de punta a punta confirma el protocolo, no el comportamiento de Resolve. Lo que hay que comprobar la primera vez:

- Que `fusion:SetPrefs` + `SavePrefs` escriben `Global.WordCaps.WordCapsAck` y `WordCapsResponse` en `Fusion.prefs` como líneas `Clave = "valor",` (si no, la app nunca ve la respuesta y dice que Resolve no responde).
- Que `AddModifier("Size", "BezierSpline")` y `SetInput(input, valor, frame)` crean fotogramas clave en el Text+ de un clip del timeline.
- La escala: la vista previa asume que el `Size` del Text+ es relativo al ancho del cuadro. Si las palabras salen más juntas o separadas que en la vista previa, ajusta *Tamaño* o *Ancho medio de letra*.
- Que whisper-cli acepta el WAV a 48 kHz que renderiza Resolve (las versiones con miniaudio lo remuestrean).

## Fuera de alcance por ahora

Efectos de sonido bajo las palabras, VFX en marcadores, macros `.setting` propias como animación, editor visual de trayectorias y paneles para otros editores.
