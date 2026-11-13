package.path = "/src/resolve/?.lua;/src/tests/lua/?.lua;" .. package.path

local core = require("wordcaps_core")
local mock = require("mock_resolve")

local mailbox, prefs = arg[1], arg[2]
local world = mock.new()
core.run(world.resolve, mock.new_fusion(prefs), mock.new_bmd(), mailbox)
