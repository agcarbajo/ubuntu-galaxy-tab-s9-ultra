-- Snapshot consumes the native PipeWire/libcamera nodes, while browsers and
-- OBS consume the V4L2 relays. Give both layers the same four stable names so
-- every application presents the same camera list. WirePlumber must expose
-- these nodes as Video/Source for Snapshot; the direct GStreamer provider is
-- omitted from libcamera-gts9u so this does not create a second camera layer.
local gts9u_cameras = {
  {
    name = "libcamera_input._base_soc_0_geniqup_8c0000_i2c_884000_camera_21",
    description = "GTS9U Front Ultra-Wide",
  },
  {
    name = "libcamera_input._base_soc_0_cci_ac16000_i2c-bus_1_camera_20",
    description = "GTS9U Front Main",
  },
  {
    name = "libcamera_input._base_soc_0_cci_ac15000_i2c-bus_1_camera_21",
    description = "GTS9U Rear Main",
  },
  {
    name = "libcamera_input._base_soc_0_cci_ac15000_i2c-bus_0_camera_21",
    description = "GTS9U Rear Ultra-Wide",
  },
}

for _, camera in ipairs(gts9u_cameras) do
  table.insert(libcamera_monitor.rules, {
    matches = {
      {
        { "node.name", "equals", camera.name },
      },
    },
    apply_properties = {
      ["media.class"] = "Video/Source",
      ["node.description"] = camera.description,
    },
  })
end
