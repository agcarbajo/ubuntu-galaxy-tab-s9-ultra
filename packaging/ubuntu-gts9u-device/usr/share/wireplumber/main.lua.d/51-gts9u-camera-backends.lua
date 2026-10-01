-- Snapshot consumes the native PipeWire/libcamera nodes, while browsers and
-- OBS consume the V4L2 relays. Give both layers the same four stable names so
-- every application presents the same camera list. WirePlumber must expose
-- these nodes as Video/Source for Snapshot; the direct GStreamer provider is
-- omitted from libcamera-gts9u so this does not create a second camera layer.
local gts9u_cameras = {
  {
    name = "libcamera_input._base_soc_0_geniqup_8c0000_i2c_884000_camera_21",
    description = "GTS9U Front Ultra-Wide",
    relay_name = "GTS9U-Front-Ultra-Wide",
  },
  {
    name = "libcamera_input._base_soc_0_cci_ac16000_i2c-bus_1_camera_20",
    description = "GTS9U Front Main",
    relay_name = "GTS9U-Front-Main",
  },
  {
    name = "libcamera_input._base_soc_0_cci_ac15000_i2c-bus_1_camera_21",
    description = "GTS9U Rear Main",
    relay_name = "GTS9U-Rear-Main",
  },
  {
    name = "libcamera_input._base_soc_0_cci_ac15000_i2c-bus_0_camera_21",
    description = "GTS9U Rear Ultra-Wide",
    relay_name = "GTS9U-Rear-Ultra-Wide",
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
  -- These compatibility outputs already consume the native libcamera nodes.
  -- Importing them back into PipeWire duplicates Snapshot's camera choices.
  -- Disable only this board's loopback devices in the V4L2 monitor; direct
  -- V4L2 clients retain /dev/video20-23 and external USB cameras are unaffected.
  table.insert(v4l2_monitor.rules, {
    matches = {
      {
        { "device.name", "matches", "v4l2_device._sys_devices_virtual_video4linux_video*" },
        { "device.description", "equals", camera.relay_name },
      },
    },
    apply_properties = {
      ["device.disabled"] = true,
    },
  })
end
