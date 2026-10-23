-- SPDX-License-Identifier: GPL-2.0-only
-- Execute stock LuCI bytecode's file handler and upgrade dispatch in isolation.
-- Every external command is replaced before either stock module is loaded.

local commands = {}
local function preload(name, value)
	package.loaded[name] = value
	local cur, bits = _G, {}
	for part in string.gmatch(name, "[^.]+") do bits[#bits + 1] = part end
	for i = 1, #bits - 1 do
		cur[bits[i]] = cur[bits[i]] or {}
		cur = cur[bits[i]]
	end
	cur[bits[#bits]] = value
end

local uci = {cursor = function()
	return {get_profile = function() return nil end}
end}
local fs = {isfile = function() return false end}
local nixio = {fs = {access = function(path)
	local f = io.open(path, "rb")
	if f then f:close(); return true end
	return false
end}}
local checker_status = 0
local sys = {
	fork_call = function(cmd)
		commands[#commands + 1] = "CHECK " .. cmd
		return checker_status
	end,
	fork_exec = function(cmd) commands[#commands + 1] = "WRITE " .. cmd end,
	call = function(cmd)
		commands[#commands + 1] = "CALL " .. cmd
		return 0
	end,
}
local controller = {
	_index = function(fn) _G.captured_dispatch = fn; return true end,
	dispatch = function(routes, request, options)
		assert(request == "upgrade" and type(options.post_hook) == "function")
		assert(type(routes.upgrade.firmware.cb) == "function")
		return routes.upgrade.firmware.cb()
	end,
}
for _, entry in ipairs({
	{"luci.model.uci", uci}, {"luci.service", {}},
	{"luci.tools.debug", {printf = function() end}}, {"luci.sys", sys},
	{"nixio", nixio}, {"luci.model.controller", controller},
	{"luci.fs", fs}, {"luci.sys.config", {}},
	{"luci.controller.admin.cloud_account", {}}, {"luci.model.log", {}},
	{"luci.model.crypto", {}}, {"luci.json", {}},
}) do preload(entry[1], entry[2]) end
-- Load the genuine stock luci.util module: it supplies string formatting to
-- the genuine stock fmup bytecode. Never preload or replace fmup itself.
os.execute = function() return 0 end
_G.dispatch = function() return true end

local http = require("luci.http")
local body = assert(io.open("/work/multipart.bin", "rb"))
local body_len = assert(body:seek("end"))
assert(body:seek("set", 0))
local env = {
  REQUEST_METHOD = "POST",
  CONTENT_TYPE = "multipart/form-data; boundary=AX3000-STOCK-MULTIPART-3B6E7C1D",
  CONTENT_LENGTH = tostring(body_len),
  QUERY_STRING = ""
}
http.context.request = http.Request(env, function()
  local block = body:read(4096)
  if not block then body:close() end
  return block
end, function() end)
local firmware = require("luci.controller.admin.firmware")
assert(type(firmware._index) == "function")
firmware._index()
assert(type(http.context.request.filehandler) == "function")
assert(type(captured_dispatch) == "function")

assert(http.formvalue("operation") == "firmware")
assert(http.formvalue("keep") == "on")
local captured = assert(io.open("/tmp/firmware.bin", "rb"))
local output = assert(io.open("/work/captured.bin", "wb"))
local total = 0
while true do
	local block = captured:read(65536)
	if not block then break end
	total = total + #block
	assert(output:write(block))
end
captured:close()
output:close()

local thread = coroutine.create(function() return captured_dispatch("upgrade") end)
repeat
  local ok, value = coroutine.resume(thread)
  assert(ok, value)
until coroutine.status(thread) == "dead"
local expected_check = 'CHECK nvrammanager -c "/tmp/firmware.bin"'
local expected_write = 'WRITE nvrammanager -u "/tmp/firmware.bin"'
local check, write
for i, command in ipairs(commands) do
	if command == expected_check then check = i end
	if command == expected_write then write = i end
end
assert(check and write and check < write and #commands == 2)
local log = assert(io.open("/work/commands.txt", "wb"))
for _, command in ipairs(commands) do assert(log:write(command, "\n")) end
log:close()
local positive_count = #commands

-- The genuine fmup bytecode must not dispatch the writer on checker failure.
commands = {}
checker_status = 1
local thread = coroutine.create(function() return captured_dispatch("upgrade") end)
repeat
  local ok, value = coroutine.resume(thread)
  assert(ok, value)
until coroutine.status(thread) == "dead"
assert(commands[1] == expected_check)
for _, command in ipairs(commands) do assert(command ~= expected_write) end
local rejected = assert(io.open("/work/rejected-commands.txt", "wb"))
for _, command in ipairs(commands) do assert(rejected:write(command, "\n")) end
rejected:close()
print("CAPTURE_BYTES", total, "STOCK_ROUTE_COMMANDS", positive_count)
