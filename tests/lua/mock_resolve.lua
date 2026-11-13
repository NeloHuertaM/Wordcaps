local mock = {}

local function new_tool()
    local tool = { inputs = {}, keyframes = {}, modifiers = {} }
    function tool:SetInput(name, value, time)
        if time == nil then
            self.inputs[name] = value
        else
            self.keyframes[name] = self.keyframes[name] or {}
            table.insert(self.keyframes[name], { time, value })
        end
        return true
    end
    function tool:AddModifier(name, kind)
        self.modifiers[name] = kind
        return true
    end
    return tool
end

local function new_item(info, without_comp)
    local item = { info = info, tool = new_tool() }
    local comp = {}
    function comp:FindToolByID(id)
        if id == "TextPlus" then
            return item.tool
        end
        return nil
    end
    function comp:FindTool()
        return nil
    end
    function item:GetStart()
        return info.recordFrame
    end
    function item:GetFusionCompCount()
        if without_comp then
            return 0
        end
        return 1
    end
    function item:GetFusionCompByIndex()
        return comp
    end
    function item:SetClipColor(color)
        self.clipColor = color
        return true
    end
    return item
end

local function new_clip(id, name, clip_type, fps)
    local clip = { id = id, name = name }
    local properties = { ["Clip Name"] = name, Type = clip_type, FPS = fps }
    function clip:GetUniqueId()
        return self.id
    end
    function clip:GetName()
        return self.name
    end
    function clip:GetClipProperty(key)
        return properties[key]
    end
    return clip
end

function mock.new(options)
    options = options or {}
    local world = {
        tracks = options.tracks or 2,
        appended = {},
        batch_calls = 0,
        batch_fails = options.batch_fails or false,
        pages = {},
        render = { jobs = {}, in_progress = false, settings = nil, presets = {} },
    }

    local template = new_clip("tpl-1", "WordCaps Word", "Fusion Title", options.template_fps or "30")
    local other = new_clip("vid-1", "interview.mov", "Video + Audio", "30")
    local sub_folder = {}
    function sub_folder:GetClipList()
        return { template }
    end
    function sub_folder:GetSubFolderList()
        return {}
    end
    local root = {}
    function root:GetClipList()
        return { other }
    end
    function root:GetSubFolderList()
        return { sub_folder }
    end

    local media_pool = {}
    function media_pool:GetRootFolder()
        return root
    end
    function media_pool:AppendToTimeline(infos)
        world.batch_calls = world.batch_calls + 1
        if world.batch_fails and #infos > 1 then
            return nil
        end
        local count = #infos
        if options.batch_partial and #infos > 1 then
            count = #infos - 1
        end
        local items = {}
        for i = 1, count do
            local info = infos[i]
            local item = new_item(info, #world.appended + 1 == options.clip_without_comp)
            items[i] = item
            table.insert(world.appended, item)
        end
        return items
    end

    local timeline = {}
    function timeline:GetName()
        return "Main"
    end
    function timeline:GetSetting(key)
        local settings = {
            timelineFrameRate = options.fps or "30",
            timelineResolutionWidth = "1080",
            timelineResolutionHeight = "1920",
        }
        return settings[key]
    end
    function timeline:GetStartFrame()
        return 108000
    end
    function timeline:GetEndFrame()
        return 108900
    end
    function timeline:GetTrackCount(kind)
        if kind == "video" then
            return world.tracks
        end
        return 1
    end
    function timeline:AddTrack(kind)
        if kind == "video" then
            world.tracks = world.tracks + 1
        end
        return true
    end
    function timeline:InsertFusionTitleIntoTimeline(name)
        world.inserted_title = name
        if options.insert_fails then
            return nil
        end
        return new_item({ recordFrame = 108000 })
    end

    local project = {}
    function project:GetName()
        return "Demo"
    end
    function project:GetCurrentTimeline()
        if options.no_timeline then
            return nil
        end
        return timeline
    end
    function project:GetSetting()
        return nil
    end
    function project:GetMediaPool()
        return media_pool
    end
    function project:IsRenderingInProgress()
        return world.render.in_progress
    end
    function project:SaveAsNewRenderPreset(name)
        world.render.presets[name] = true
        return true
    end
    function project:LoadRenderPreset(name)
        world.render.loaded = name
        return name ~= "Audio Only" or options.has_audio_preset == true
    end
    function project:DeleteRenderPreset(name)
        world.render.presets[name] = nil
        return true
    end
    function project:SetCurrentRenderFormatAndCodec(format, codec)
        world.render.format = format .. "/" .. codec
        return true
    end
    function project:SetCurrentRenderMode(mode)
        world.render.mode = mode
        return true
    end
    function project:SetRenderSettings(settings)
        world.render.settings = settings
        return true
    end
    function project:AddRenderJob()
        table.insert(world.render.jobs, "job-1")
        return "job-1"
    end
    function project:StartRendering()
        world.render.start_attempts = (world.render.start_attempts or 0) + 1
        if options.start_fails then
            return false
        end
        world.render.in_progress = true
        return true
    end
    function project:GetRenderJobStatus()
        return world.render.status or { JobStatus = "Complete", CompletionPercentage = 100 }
    end
    function project:DeleteRenderJob(id)
        world.render.deleted = id
        return true
    end

    local manager = {}
    function manager:GetCurrentProject()
        if options.no_project then
            return nil
        end
        return project
    end

    local resolve = {}
    function resolve:GetProjectManager()
        return manager
    end
    function resolve:GetProductName()
        return "DaVinci Resolve"
    end
    function resolve:GetVersionString()
        return "21.1.0"
    end
    function resolve:OpenPage(page)
        table.insert(world.pages, page)
        return true
    end

    world.resolve = resolve
    world.timeline = timeline
    return world
end

function mock.new_fusion(prefs_path)
    local fusion = { prefs = {} }
    function fusion:SetPrefs(key, value)
        self.prefs[key] = value
        return true
    end
    function fusion:GetPrefs(key)
        return self.prefs[key]
    end
    function fusion:SavePrefs()
        if not prefs_path then
            return true
        end
        local lines = { "{", "\tGlobal = {", "\t\tWordCaps = {" }
        for key, value in pairs(self.prefs) do
            local short = key:match("^Global%.WordCaps%.(.+)$")
            if short then
                table.insert(lines, string.format('\t\t\t%s = "%s",', short, value))
            end
        end
        table.insert(lines, "\t\t},")
        table.insert(lines, "\t},")
        table.insert(lines, "}")
        local temporary = prefs_path .. ".tmp"
        local file = assert(io.open(temporary, "w"))
        file:write(table.concat(lines, "\n"))
        file:close()
        assert(os.rename(temporary, prefs_path))
        return true
    end
    return fusion
end

function mock.new_bmd()
    local bmd = {}
    function bmd.fileexists(path)
        local file = io.open(path, "r")
        if file then
            file:close()
            return true
        end
        return false
    end
    function bmd.wait(seconds)
        os.execute("sleep " .. tostring(seconds))
    end
    return bmd
end

return mock
