/* Compile with -DRELAY_SOURCE='"/path/to/patched/src/v4l2-relayd.c"'.
 * Uses real GStreamer with a synthetic source and fakesink; no camera access.
 */
#define main relay_main
#include RELAY_SOURCE
#undef main

static gint frames;

static void count_frame (GstElement *sink, GstBuffer *buffer, GstPad *pad,
                         gpointer data)
{
  g_atomic_int_inc (&frames);
}

static void pump (guint milliseconds)
{
  gint64 until = g_get_monotonic_time () + milliseconds * 1000;
  while (g_get_monotonic_time () < until) {
    while (g_main_context_iteration (NULL, FALSE)) {}
    g_usleep (1000);
  }
}

int main (int argc, char **argv)
{
  GstElement *sink;
  gint idle_frames, restarted;
  gst_init (&argc, &argv);
  GST_DEBUG_CATEGORY_INIT (GST_CAT_DEFAULT, "V4L2_RELAYD", 0, "test");
  output_pipeline = gst_parse_launch (
      "appsrc name=appsrc is-live=true format=time caps=video/x-raw,format=YUY2,width=640,height=480,framerate=30/1 "
      "! fakesink name=sink sync=false signal-handoffs=true", NULL);
  sink = gst_bin_get_by_name (GST_BIN (output_pipeline), "sink");
  g_signal_connect (sink, "handoff", G_CALLBACK (count_frame), NULL);
  gst_object_unref (sink);
  gst_element_set_state (output_pipeline, GST_STATE_PLAYING);
  opt_splash = "videotestsrc num-buffers=1 pattern=black ! video/x-raw,format=YUY2,width=640,height=480,framerate=30/1 ! imagefreeze is-live=true";

  splash_pipeline_set_active (TRUE);
  pump (300);
  g_assert_cmpint (g_atomic_int_get (&frames), >=, 3);
  input_client_active = FALSE;
  input_pipeline_destroy (NULL);
  pump (100); /* Drain already queued output. */
  idle_frames = g_atomic_int_get (&frames);
  pump (700);
  g_assert_cmpint (g_atomic_int_get (&frames), ==, idle_frames);
  g_assert_cmpint (GST_STATE (output_pipeline), ==, GST_STATE_PLAYING);

  /* A preempted reader needs paced black frames while another relay owns ISP. */
  input_preempted = TRUE;
  input_pipeline_request_enable ();
  pump (300);
  restarted = g_atomic_int_get (&frames) - idle_frames;
  g_assert_cmpint (restarted, >=, 3);
  g_assert_cmpint (restarted, <=, 15); /* No backlog burst after the idle gap. */
  g_assert_cmpuint (input_enable_timeout_id, ==, 0);
  input_pipeline_destroy (NULL); /* Still a client: keep its splash alive. */
  idle_frames = g_atomic_int_get (&frames);
  pump (200);
  g_assert_cmpint (g_atomic_int_get (&frames), >, idle_frames);

  input_client_active = FALSE;
  input_pipeline_disable ();
  pump (700);
  idle_frames = g_atomic_int_get (&frames);
  pump (200);
  g_assert_cmpint (g_atomic_int_get (&frames), ==, idle_frames);
  gst_element_set_state (splash_pipeline, GST_STATE_NULL);
  gst_element_set_state (output_pipeline, GST_STATE_NULL);
  g_source_remove (splash_bus_watch_id);
  gst_object_unref (splash_pipeline);
  gst_object_unref (output_pipeline);
  g_print ("PASS: priming, no idle frames, paced restart, preempted reader, delayed close\n");
  return 0;
}
