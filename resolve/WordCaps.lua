local core_path = [==[__WORDCAPS_CORE_PATH__]==]
local mailbox_dir = [==[__WORDCAPS_MAILBOX_DIR__]==]

if not bmd.fileexists(core_path) then
    print("[WordCaps] No encuentro " .. core_path)
    print("[WordCaps] Vuelve a instalar el script desde la app de WordCaps.")
    return
end

local core = assert(loadfile(core_path))()
core.run(resolve or Resolve(), fusion or fu, bmd, mailbox_dir)
