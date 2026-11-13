local M = {}

M.VERSION = "0.1.0"

local KEY_ACK = "Global.WordCaps.WordCapsAck"
local KEY_RESPONSE = "Global.WordCaps.WordCapsResponse"
local KEY_PROGRESS = "Global.WordCaps.WordCapsProgress"
local KEY_OWNER = "Global.WordCaps.WordCapsOwner"

local STALE_REQUEST_SECONDS = 120
local OWNER_CHECK_TICKS = 10
local POLL_SECONDS = 0.05
local PROGRESS_EVERY = 25
local VIDEO_TRACK = "video"
local FRAME_RATE_SETTING = "timelineFrameRate"
local LOG_PREFIX = "[WordCaps] "
local CLIP_NAME_PROPERTY = "Clip Name"

local EXPORT_STATE = {
    idle = "idle",
    rendering = "rendering",
    failed = "failed",
    done = "done",
}

local FUSION_TITLE_TYPES = {
    ["Fusion Title"] = true,
    ["Generator"] = true,
    ["Título – Fusion"] = true,
    ["Título Fusion"] = true,
    ["Titre Fusion"] = true,
    ["Fusion Titel"] = true,
    ["Titolo Fusion"] = true,
}

local function json_string(s)
    local escaped = s:gsub('[%c"\\\128-\255]', function(c)
        local b = c:byte()
        if c == '"' then
            return '\\"'
        elseif c == "\\" then
            return "\\\\"
        elseif b >= 128 then
            return string.format("\\u%04x", 0xE000 + b)
        end
        return string.format("\\u%04x", b)
    end)
    return '"' .. escaped .. '"'
end

local function is_array(t)
    local count = 0
    for _ in pairs(t) do
        count = count + 1
    end
    return count == #t
end

local function json_encode(value)
    local kind = type(value)
    if value == nil then
        return "null"
    elseif kind == "boolean" then
        return value and "true" or "false"
    elseif kind == "number" then
        if value ~= value or value == math.huge or value == -math.huge then
            return "null"
        end
        if value == math.floor(value) and math.abs(value) < 1e15 then
            return string.format("%d", value)
        end
        return string.format("%.10g", value)
    elseif kind == "string" then
        return json_string(value)
    elseif kind == "table" then
        local parts = {}
        if is_array(value) then
            for i = 1, #value do
                parts[i] = json_encode(value[i])
            end
            return "[" .. table.concat(parts, ",") .. "]"
        end
        for k, v in pairs(value) do
            parts[#parts + 1] = json_string(tostring(k)) .. ":" .. json_encode(v)
        end
        return "{" .. table.concat(parts, ",") .. "}"
    end
    return json_string(tostring(value))
end

M.json_encode = json_encode

local BASE64_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"

local function base64_encode(data)
    local out = {}
    for i = 1, #data, 3 do
        local a, b, c = data:byte(i, i + 2)
        local n = a * 65536 + (b or 0) * 256 + (c or 0)
        local c1 = math.floor(n / 262144) % 64
        local c2 = math.floor(n / 4096) % 64
        local c3 = math.floor(n / 64) % 64
        local c4 = n % 64
        out[#out + 1] = BASE64_ALPHABET:sub(c1 + 1, c1 + 1)
            .. BASE64_ALPHABET:sub(c2 + 1, c2 + 1)
            .. (b and BASE64_ALPHABET:sub(c3 + 1, c3 + 1) or "=")
            .. (c and BASE64_ALPHABET:sub(c4 + 1, c4 + 1) or "=")
    end
    return table.concat(out)
end

M.base64_encode = base64_encode

local function fail(message)
    error(message, 0)
end

local function current_project(context)
    local manager = context.resolve:GetProjectManager()
    local project = manager and manager:GetCurrentProject()
    if not project then
        fail("No hay ningún proyecto abierto en DaVinci Resolve.")
    end
    return project
end

local function current_timeline(context)
    local project = current_project(context)
    local timeline = project:GetCurrentTimeline()
    if not timeline then
        fail("El proyecto no tiene ningún timeline abierto.")
    end
    return project, timeline
end

local function numeric_setting(timeline, project, key)
    local value = tonumber(timeline:GetSetting(key))
    if value == nil then
        value = tonumber(project:GetSetting(key))
    end
    return value
end

local function is_live_item(item)
    if item == nil then
        return false
    end
    local ok, start = pcall(function()
        return item:GetStart()
    end)
    return ok and start ~= nil
end

local function each_clip(folder, visit)
    for _, clip in ipairs(folder:GetClipList() or {}) do
        visit(clip)
    end
    for _, sub in ipairs(folder:GetSubFolderList() or {}) do
        each_clip(sub, visit)
    end
end

local function is_title_clip(clip)
    local clip_type = clip:GetClipProperty("Type")
    local name = clip:GetClipProperty(CLIP_NAME_PROPERTY) or clip:GetName() or ""
    return FUSION_TITLE_TYPES[clip_type] == true or name:find("^WordCaps") ~= nil
end

local function find_template(media_pool, template_id, template_name)
    local by_name = nil
    local by_id = nil
    each_clip(media_pool:GetRootFolder(), function(clip)
        if by_id then
            return
        end
        if template_id and template_id ~= "" and clip:GetUniqueId() == template_id then
            by_id = clip
        elseif by_name == nil and template_name and
            (clip:GetClipProperty(CLIP_NAME_PROPERTY) == template_name or clip:GetName() == template_name) then
            by_name = clip
        end
    end)
    return by_id or by_name
end

local function find_text_tool(item)
    local count = item:GetFusionCompCount()
    if not count or count < 1 then
        fail("El clip no tiene composición de Fusion: la plantilla no es un Text+.")
    end
    local comp = item:GetFusionCompByIndex(1)
    local tool = comp:FindToolByID("TextPlus") or comp:FindTool("Template")
    if not tool then
        fail("La composición de la plantilla no contiene ninguna herramienta Text+.")
    end
    return tool
end

local function apply_inputs(tool, inputs)
    for name, value in pairs(inputs or {}) do
        if type(value) == "table" then
            tool:SetInput(name, { value[1], value[2] })
        else
            tool:SetInput(name, value)
        end
    end
end

local function apply_keys(tool, keys)
    for _, key in ipairs(keys or {}) do
        tool:AddModifier(key.input, "BezierSpline")
        for _, point in ipairs(key.points) do
            tool:SetInput(key.input, point[2], point[1])
        end
    end
end

local export_job = nil

local function snapshot_render_state(project)
    local preset = "WordCaps restore " .. tostring(os.time())
    local ok, saved = pcall(function()
        return project:SaveAsNewRenderPreset(preset)
    end)
    if ok and saved then
        return preset
    end
    return nil
end

local function cleanup_export(context, project)
    if export_job == nil then
        return
    end
    pcall(function()
        project:DeleteRenderJob(export_job.pid)
    end)
    if export_job.preset then
        pcall(function()
            project:LoadRenderPreset(export_job.preset)
        end)
        pcall(function()
            project:DeleteRenderPreset(export_job.preset)
        end)
    end
    pcall(function()
        context.resolve:OpenPage("edit")
    end)
    export_job = nil
end

local handlers = {}

function handlers.Ping(context)
    return {
        bridge = M.VERSION,
        product = context.resolve:GetProductName(),
        version = context.resolve:GetVersionString(),
    }
end

function handlers.GetTimelineInfo(context)
    local project, timeline = current_timeline(context)
    return {
        project = project:GetName(),
        timeline = timeline:GetName(),
        fps = numeric_setting(timeline, project, FRAME_RATE_SETTING),
        width = numeric_setting(timeline, project, "timelineResolutionWidth"),
        height = numeric_setting(timeline, project, "timelineResolutionHeight"),
        startFrame = timeline:GetStartFrame(),
        endFrame = timeline:GetEndFrame(),
        videoTracks = timeline:GetTrackCount(VIDEO_TRACK),
    }
end

function handlers.ListTemplates(context)
    local media_pool = current_project(context):GetMediaPool()
    local templates = {}
    each_clip(media_pool:GetRootFolder(), function(clip)
        if is_title_clip(clip) then
            templates[#templates + 1] = {
                id = clip:GetUniqueId(),
                name = clip:GetClipProperty(CLIP_NAME_PROPERTY) or clip:GetName(),
            }
        end
    end)
    return { templates = templates }
end

function handlers.CreateTemplateClip(context)
    local _, timeline = current_timeline(context)
    local item = timeline:InsertFusionTitleIntoTimeline("Text+")
    if not is_live_item(item) then
        fail("Resolve no pudo insertar un Text+ en el timeline.")
    end
    pcall(function()
        find_text_tool(item):SetInput("StyledText", "WordCaps")
    end)
    return { inserted = true }
end

function handlers.ExportAudio(context, args)
    local project, timeline = current_timeline(context)
    if export_job ~= nil then
        cleanup_export(context, project)
    end
    if project:IsRenderingInProgress() then
        fail("Resolve ya está renderizando. Espera a que termine e inténtalo de nuevo.")
    end

    context.resolve:OpenPage("deliver")
    local job = { preset = snapshot_render_state(project), dir = args.dir, name = args.name }
    export_job = job

    local ok, err = pcall(function()
        project:LoadRenderPreset("Audio Only")
        project:SetCurrentRenderFormatAndCodec("wav", "LinearPCM")
        project:SetCurrentRenderMode(1)
        local start_frame = timeline:GetStartFrame()
        project:SetRenderSettings({
            SelectAllFrames = false,
            MarkIn = start_frame,
            MarkOut = math.max(start_frame, timeline:GetEndFrame() - 1),
            TargetDir = args.dir,
            CustomName = args.name,
            ExportVideo = false,
            ExportAudio = true,
            AudioBitDepth = 16,
            AudioSampleRate = 48000,
        })
        job.pid = project:AddRenderJob()
        if not job.pid then
            fail("Resolve no aceptó el trabajo de render del audio.")
        end
        local started = project:StartRendering(job.pid)
        if not started then
            context.bmd.wait(0.5)
            started = project:StartRendering(job.pid)
        end
        if not started then
            fail("Resolve no pudo empezar a renderizar el audio.")
        end
    end)

    if not ok then
        cleanup_export(context, project)
        error(err, 0)
    end
    return { started = true }
end

function handlers.GetExportStatus(context)
    local project = current_project(context)
    if export_job == nil then
        return { state = EXPORT_STATE.idle }
    end
    local status = nil
    pcall(function()
        status = project:GetRenderJobStatus(export_job.pid)
    end)
    local percentage = type(status) == "table" and status.CompletionPercentage or nil
    if project:IsRenderingInProgress() then
        return { state = EXPORT_STATE.rendering, progress = percentage or 0 }
    end

    local job = export_job
    cleanup_export(context, project)
    local job_error = type(status) == "table" and status.Error or nil
    if job_error ~= nil and tostring(job_error) ~= "" then
        return { state = EXPORT_STATE.failed, error = tostring(job_error) }
    end
    if type(percentage) == "number" and percentage < 100 then
        return { state = EXPORT_STATE.failed, error = "El render se detuvo al " .. tostring(percentage) .. "%." }
    end
    return { state = EXPORT_STATE.done, dir = job.dir, name = job.name }
end

local function build_clip_infos(clips, template, template_fps, timeline_fps, base_track)
    local infos = {}
    for i, clip in ipairs(clips) do
        local source_frames = math.max(1, math.floor(clip.duration * template_fps / timeline_fps + 0.5))
        infos[i] = {
            mediaPoolItem = template,
            mediaType = 1,
            startFrame = 0,
            endFrame = source_frames,
            recordFrame = math.floor(clip.record + 0.5),
            trackIndex = base_track + clip.lane,
        }
    end
    return infos
end

local function append_clips(media_pool, infos)
    local ok, items = pcall(function()
        return media_pool:AppendToTimeline(infos)
    end)
    if ok and type(items) == "table" and #items > 0 then
        if #items ~= #infos then
            fail("Resolve colocó " .. #items .. " de " .. #infos .. " clips y no se puede saber cuál es cuál. "
                .. "Deshaz con Ctrl+Z y vuelve a intentarlo.")
        end
        return items
    end
    items = {}
    for i, info in ipairs(infos) do
        local single_ok, placed = pcall(function()
            return media_pool:AppendToTimeline({ info })
        end)
        if single_ok and type(placed) == "table" then
            items[i] = placed[1]
        end
    end
    return items
end

function handlers.PlaceCaptions(context, args, request_id)
    local project, timeline = current_timeline(context)
    local media_pool = project:GetMediaPool()
    local template = find_template(media_pool, args.templateId, args.templateName)
    if not template then
        fail("No encuentro la plantilla '" .. tostring(args.templateName) .. "' en el Media Pool.")
    end

    local timeline_fps = numeric_setting(timeline, project, FRAME_RATE_SETTING)
    local template_fps = tonumber(template:GetClipProperty("FPS")) or timeline_fps

    local base_track = timeline:GetTrackCount(VIDEO_TRACK)
    for _ = 1, args.lanes do
        timeline:AddTrack(VIDEO_TRACK)
    end
    if timeline:GetTrackCount(VIDEO_TRACK) ~= base_track + args.lanes then
        fail("Resolve no pudo crear las pistas de vídeo para los subtítulos.")
    end

    local clips = args.clips
    local items = append_clips(media_pool, build_clip_infos(clips, template, template_fps, timeline_fps, base_track))

    local placed, failed, first_error = 0, 0, nil
    for i, clip in ipairs(clips) do
        local item = items[i]
        local ok, err = pcall(function()
            if not is_live_item(item) then
                fail("Resolve no colocó el clip en el timeline.")
            end
            local tool = find_text_tool(item)
            apply_inputs(tool, clip.inputs)
            apply_keys(tool, clip.keys)
            if clip.clipColor then
                item:SetClipColor(clip.clipColor)
            end
        end)
        if ok then
            placed = placed + 1
        else
            failed = failed + 1
            first_error = first_error or tostring(err)
        end
        if i % PROGRESS_EVERY == 0 then
            context.write_pref(KEY_PROGRESS, request_id .. ":" .. i .. "/" .. #clips)
        end
    end

    local tracks = {}
    for lane = 1, args.lanes do
        tracks[lane] = base_track + lane
    end
    return { placed = placed, failed = failed, firstError = first_error, tracks = tracks }
end

M.handlers = handlers

local function dispatch(context, request)
    local handler = handlers[request.func]
    if not handler then
        return { error = "Función desconocida: " .. tostring(request.func) }
    end
    local ok, result = pcall(handler, context, request.args or {}, request.id)
    if not ok then
        return { error = tostring(result) }
    end
    return { result = result or {} }
end

M.dispatch = dispatch

local function request_age_seconds(request_id)
    local millis = tonumber(request_id:match("^(%d+)"))
    if millis == nil then
        return 0
    end
    return os.time() - math.floor(millis / 1000)
end

function M.new_context(resolve, fusion, bmd)
    local context = { resolve = resolve, fusion = fusion, bmd = bmd }
    function context.write_pref(key, value)
        for _ = 1, 5 do
            local ok = pcall(function()
                fusion:SetPrefs(key, value)
                fusion:SavePrefs()
            end)
            if ok then
                return
            end
            bmd.wait(0.05)
        end
    end
    return context
end

function M.handle_request(context, request)
    context.write_pref(KEY_ACK, request.id)
    local body = dispatch(context, request)
    context.write_pref(KEY_RESPONSE, request.id .. ":" .. base64_encode(json_encode(body)))
end

function M.run(resolve, fusion, bmd, mailbox_dir)
    local context = M.new_context(resolve, fusion, bmd)
    local owner = tostring(os.time()) .. tostring({})
    fusion:SetPrefs(KEY_OWNER, owner)
    local request_file = mailbox_dir .. "/request.lua"
    local last_id = nil
    local tick = 0
    print(LOG_PREFIX .. "Puente activo (v" .. M.VERSION .. "). Buzón: " .. mailbox_dir)

    while true do
        tick = tick + 1
        if tick >= OWNER_CHECK_TICKS then
            tick = 0
            if fusion:GetPrefs(KEY_OWNER) ~= owner then
                print(LOG_PREFIX .. "Otra instancia del puente ha tomado el control. Cerrando esta.")
                return
            end
        end

        if bmd.fileexists(request_file) then
            local chunk = loadfile(request_file)
            local ok, request = false, nil
            if chunk then
                ok, request = pcall(chunk)
            end
            if ok and type(request) == "table" and type(request.id) == "string" and request.id ~= last_id then
                last_id = request.id
                if request_age_seconds(request.id) <= STALE_REQUEST_SECONDS then
                    M.handle_request(context, request)
                end
            end
        end
        bmd.wait(POLL_SECONDS)
    end
end

return M
