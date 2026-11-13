package.path = "/src/resolve/?.lua;/src/tests/lua/?.lua;" .. package.path

local core = require("wordcaps_core")
local mock = require("mock_resolve")

local failures = 0
local passed = 0

local function test(name, body)
    local ok, err = pcall(body)
    if ok then
        passed = passed + 1
        print("ok   " .. name)
    else
        failures = failures + 1
        print("FAIL " .. name .. ": " .. tostring(err))
    end
end

local function eq(actual, expected, label)
    if actual ~= expected then
        error((label or "value") .. ": expected " .. tostring(expected) .. ", got " .. tostring(actual), 2)
    end
end

local function context(world)
    return core.new_context(world.resolve, mock.new_fusion(nil), mock.new_bmd())
end

local function clip(record, duration, lane, text)
    return {
        text = text,
        record = record,
        duration = duration,
        lane = lane,
        inputs = { StyledText = text, Size = 0.08, Center = { 0.4, 0.3 }, Red1 = 1 },
        keys = { { input = "Size", points = { { 0, 0 }, { 3, 0.09 }, { 6, 0.08 } } } },
        clipColor = "Orange",
    }
end

test("json_encode escapes quotes, control bytes and marks every byte >= 0x80", function()
    eq(core.json_encode({ a = 'x"\n' }), '{"a":"x\\"\\u000a"}')
    eq(core.json_encode("ñ"), '"\\ue0c3\\ue0b1"')
    eq(core.json_encode({ 1, 2.5, true }), "[1,2.5,true]")
    eq(core.json_encode(0 / 0), "null")
end)

test("base64_encode pads like RFC 4648", function()
    eq(core.base64_encode(""), "")
    eq(core.base64_encode("f"), "Zg==")
    eq(core.base64_encode("fo"), "Zm8=")
    eq(core.base64_encode("foobar"), "Zm9vYmFy")
end)

test("unknown function is answered with an error body", function()
    local body = core.dispatch(context(mock.new()), { id = "1-1", func = "Nope", args = {} })
    eq(body.error, "Función desconocida: Nope")
end)

test("GetTimelineInfo reports numeric frame data", function()
    local body = core.dispatch(context(mock.new()), { id = "1-1", func = "GetTimelineInfo", args = {} })
    eq(body.result.fps, 30)
    eq(body.result.width, 1080)
    eq(body.result.startFrame, 108000)
end)

test("handlers explain when Resolve has no project open", function()
    local body = core.dispatch(context(mock.new({ no_project = true })), { id = "1-1", func = "GetTimelineInfo", args = {} })
    eq(body.error, "No hay ningún proyecto abierto en DaVinci Resolve.")
end)

test("handlers explain when the project has no timeline open", function()
    local body = core.dispatch(context(mock.new({ no_timeline = true })), { id = "1-1", func = "GetTimelineInfo", args = {} })
    eq(body.error, "El proyecto no tiene ningún timeline abierto.")
end)

test("ListTemplates walks sub folders and keeps only Fusion titles", function()
    local body = core.dispatch(context(mock.new()), { id = "1-1", func = "ListTemplates", args = {} })
    eq(#body.result.templates, 1)
    eq(body.result.templates[1].name, "WordCaps Word")
    eq(body.result.templates[1].id, "tpl-1")
end)

test("PlaceCaptions adds one new track per lane and appends on them", function()
    local world = mock.new({ tracks = 2 })
    local args = {
        templateId = "tpl-1",
        lanes = 2,
        clips = { clip(108010, 20, 1, "HOLA"), clip(108015, 15, 2, "MUNDO") },
    }
    local body = core.dispatch(context(world), { id = "1-1", func = "PlaceCaptions", args = args })
    eq(body.error, nil, "error")
    eq(world.tracks, 4, "track count")
    eq(body.result.placed, 2)
    eq(body.result.tracks[1], 3)
    eq(body.result.tracks[2], 4)
    eq(world.batch_calls, 1)
    local first = world.appended[1]
    eq(first.info.trackIndex, 3)
    eq(first.info.recordFrame, 108010)
    eq(first.info.endFrame, 20)
    eq(first.info.startFrame, 0)
    eq(world.appended[2].info.trackIndex, 4)
end)

test("PlaceCaptions applies inputs, point inputs and keyframes", function()
    local world = mock.new()
    local args = { templateName = "WordCaps Word", lanes = 1, clips = { clip(108010, 20, 1, "HOLA") } }
    core.dispatch(context(world), { id = "1-1", func = "PlaceCaptions", args = args })
    local tool = world.appended[1].tool
    eq(tool.inputs.StyledText, "HOLA")
    eq(tool.inputs.Center[1], 0.4)
    eq(tool.inputs.Center[2], 0.3)
    eq(tool.modifiers.Size, "BezierSpline")
    eq(#tool.keyframes.Size, 3)
    eq(tool.keyframes.Size[2][1], 3)
    eq(tool.keyframes.Size[2][2], 0.09)
    eq(world.appended[1].clipColor, "Orange")
end)

test("PlaceCaptions converts durations to template frames when frame rates differ", function()
    local world = mock.new({ fps = "60", template_fps = "30" })
    local args = { templateId = "tpl-1", lanes = 1, clips = { clip(108010, 20, 1, "HOLA") } }
    core.dispatch(context(world), { id = "1-1", func = "PlaceCaptions", args = args })
    eq(world.appended[1].info.endFrame, 10)
end)

test("PlaceCaptions falls back to one append per clip when the batch is refused", function()
    local world = mock.new({ batch_fails = true })
    local args = {
        templateId = "tpl-1",
        lanes = 2,
        clips = { clip(108010, 20, 1, "HOLA"), clip(108015, 15, 2, "MUNDO") },
    }
    local body = core.dispatch(context(world), { id = "1-1", func = "PlaceCaptions", args = args })
    eq(body.result.placed, 2)
    eq(world.batch_calls, 3)
end)

test("PlaceCaptions refuses to style clips when the batch returns fewer items than requested", function()
    local world = mock.new({ batch_partial = true })
    local args = {
        templateId = "tpl-1",
        lanes = 2,
        clips = { clip(108010, 20, 1, "HOLA"), clip(108015, 15, 2, "MUNDO") },
    }
    local body = core.dispatch(context(world), { id = "1-1", func = "PlaceCaptions", args = args })
    eq(body.result, nil, "result")
    eq(body.error:find("colocó 1 de 2 clips", 1, true) ~= nil, true, "error mentions counts")
    eq(world.appended[1].tool.inputs.StyledText, nil, "no text written")
end)

test("PlaceCaptions prefers the template id and falls back to the name when the id is gone", function()
    local by_id = mock.new()
    core.dispatch(context(by_id), { id = "1-1", func = "PlaceCaptions",
        args = { templateId = "tpl-1", templateName = "Nope", lanes = 1, clips = { clip(108010, 20, 1, "A") } } })
    eq(by_id.appended[1].info.mediaPoolItem:GetUniqueId(), "tpl-1")

    local by_name = mock.new()
    core.dispatch(context(by_name), { id = "1-2", func = "PlaceCaptions",
        args = { templateId = "gone", templateName = "WordCaps Word", lanes = 1, clips = { clip(108010, 20, 1, "A") } } })
    eq(by_name.appended[1].info.mediaPoolItem:GetUniqueId(), "tpl-1")
end)

test("PlaceCaptions fails clearly when the template is missing", function()
    local world = mock.new()
    local args = { templateName = "Nope", lanes = 1, clips = { clip(108010, 20, 1, "HOLA") } }
    local body = core.dispatch(context(world), { id = "1-1", func = "PlaceCaptions", args = args })
    eq(body.error, "No encuentro la plantilla 'Nope' en el Media Pool.")
    eq(world.tracks, 2, "no tracks added")
end)

test("ExportAudio renders WAV for the whole timeline and status cleans up", function()
    local world = mock.new()
    local bridge_context = context(world)
    local body = core.dispatch(bridge_context, { id = "1-1", func = "ExportAudio", args = { dir = "/tmp/out", name = "audio" } })
    eq(body.error, nil, "error")
    eq(world.render.format, "wav/LinearPCM")
    eq(world.render.settings.MarkIn, 108000)
    eq(world.render.settings.MarkOut, 108899)
    eq(world.render.settings.ExportVideo, false)
    eq(world.render.settings.TargetDir, "/tmp/out")

    local rendering = core.dispatch(bridge_context, { id = "1-2", func = "GetExportStatus", args = {} })
    eq(rendering.result.state, "rendering")

    world.render.in_progress = false
    local done = core.dispatch(bridge_context, { id = "1-3", func = "GetExportStatus", args = {} })
    eq(done.result.state, "done")
    eq(done.result.name, "audio")
    eq(world.render.deleted, "job-1")
    eq(world.pages[#world.pages], "edit")
    eq(next(world.render.presets), nil, "snapshot preset deleted")
end)

test("GetExportStatus reports a failed render with Resolve's error", function()
    local world = mock.new()
    local bridge_context = context(world)
    core.dispatch(bridge_context, { id = "1-1", func = "ExportAudio", args = { dir = "/tmp/out", name = "audio" } })
    world.render.in_progress = false
    world.render.status = { JobStatus = "Failed", CompletionPercentage = 40, Error = "Disk full" }
    local body = core.dispatch(bridge_context, { id = "1-2", func = "GetExportStatus", args = {} })
    eq(body.result.state, "failed")
    eq(body.result.error, "Disk full")
end)

test("ExportAudio first cleans up an earlier export that was never polled to the end", function()
    local first = mock.new()
    local bridge_context = context(first)
    core.dispatch(bridge_context, { id = "1-1", func = "ExportAudio", args = { dir = "/x", name = "a" } })
    first.render.in_progress = false
    core.dispatch(bridge_context, { id = "1-2", func = "ExportAudio", args = { dir = "/x", name = "b" } })
    eq(first.render.deleted, "job-1")
    first.render.in_progress = false
    local status = core.dispatch(bridge_context, { id = "1-3", func = "GetExportStatus", args = {} })
    eq(status.result.name, "b")
end)

test("ExportAudio refuses while another render runs", function()
    local world = mock.new()
    world.render.in_progress = true
    local body = core.dispatch(context(world), { id = "1-1", func = "ExportAudio", args = { dir = "/x", name = "a" } })
    eq(body.error, "Resolve ya está renderizando. Espera a que termine e inténtalo de nuevo.")
end)

test("CreateTemplateClip inserts a Text+ title", function()
    local world = mock.new()
    local body = core.dispatch(context(world), { id = "1-1", func = "CreateTemplateClip", args = {} })
    eq(body.result.inserted, true)
    eq(world.inserted_title, "Text+")
end)

test("PlaceCaptions counts a clip without a Text+ composition as failed and keeps going", function()
    local world = mock.new({ clip_without_comp = 2 })
    local args = {
        templateId = "tpl-1",
        lanes = 2,
        clips = { clip(108010, 20, 1, "HOLA"), clip(108015, 15, 2, "MUNDO") },
    }
    local body = core.dispatch(context(world), { id = "1-1", func = "PlaceCaptions", args = args })
    eq(body.result.placed, 1)
    eq(body.result.failed, 1)
    eq(body.result.firstError, "El clip no tiene composición de Fusion: la plantilla no es un Text+.")
end)

test("GetExportStatus reports a render that stopped below 100 percent as failed", function()
    local world = mock.new()
    local bridge_context = context(world)
    core.dispatch(bridge_context, { id = "1-1", func = "ExportAudio", args = { dir = "/tmp/out", name = "audio" } })
    world.render.in_progress = false
    world.render.status = { JobStatus = "Cancelled", CompletionPercentage = 40 }
    local body = core.dispatch(bridge_context, { id = "1-2", func = "GetExportStatus", args = {} })
    eq(body.result.state, "failed")
    eq(body.result.error, "El render se detuvo al 40%.")
end)

test("ExportAudio retries once, then cleans up the job and restores the render settings", function()
    local world = mock.new({ start_fails = true })
    local body = core.dispatch(context(world), { id = "1-1", func = "ExportAudio", args = { dir = "/x", name = "a" } })
    eq(body.error, "Resolve no pudo empezar a renderizar el audio.")
    eq(world.render.start_attempts, 2)
    eq(world.render.deleted, "job-1")
    eq(next(world.render.presets), nil, "snapshot preset deleted")
    eq(world.pages[#world.pages], "edit")
    local status = core.dispatch(context(world), { id = "1-2", func = "GetExportStatus", args = {} })
    eq(status.result.state, "idle")
end)

test("CreateTemplateClip reports when Resolve inserts nothing", function()
    local world = mock.new({ insert_fails = true })
    local body = core.dispatch(context(world), { id = "1-1", func = "CreateTemplateClip", args = {} })
    eq(body.error, "Resolve no pudo insertar un Text+ en el timeline.")
end)

local MAILBOX = "/tmp/wordcaps-test-mailbox"
local OWNER_KEY = "Global.WordCaps.WordCapsOwner"

local function write_request(id)
    os.execute("mkdir -p " .. MAILBOX)
    local file = assert(io.open(MAILBOX .. "/request.lua", "w"))
    file:write('return { id = "' .. id .. '", func = "Ping", args = {} }')
    file:close()
end

local function run_bridge_until_taken_over(fusion, take_over_at_wait)
    local waits = 0
    local bmd = mock.new_bmd()
    bmd.wait = function()
        waits = waits + 1
        if waits == take_over_at_wait then
            fusion.prefs[OWNER_KEY] = "another instance"
        end
        if waits > 200 then
            error("bridge loop did not stop after another instance took over")
        end
    end
    core.run(mock.new().resolve, fusion, bmd, MAILBOX)
    return waits
end

test("the bridge loop stops when another instance takes over", function()
    os.remove(MAILBOX .. "/request.lua")
    local waits = run_bridge_until_taken_over(mock.new_fusion(nil), 1)
    eq(waits, 9)
end)

test("the bridge loop answers a fresh request", function()
    local id = tostring(os.time() * 1000) .. "-1"
    write_request(id)
    local fusion = mock.new_fusion(nil)
    run_bridge_until_taken_over(fusion, 1)
    eq(fusion.prefs["Global.WordCaps.WordCapsAck"], id)
    eq(fusion.prefs["Global.WordCaps.WordCapsResponse"]:sub(1, #id + 1), id .. ":")
end)

test("the bridge loop ignores a request older than two minutes", function()
    write_request("1000-1")
    local fusion = mock.new_fusion(nil)
    run_bridge_until_taken_over(fusion, 1)
    eq(fusion.prefs["Global.WordCaps.WordCapsAck"], nil)
    eq(fusion.prefs["Global.WordCaps.WordCapsResponse"], nil)
    os.remove(MAILBOX .. "/request.lua")
end)

print(string.format("%d passed, %d failed", passed, failures))
os.exit(failures == 0 and 0 or 1)
