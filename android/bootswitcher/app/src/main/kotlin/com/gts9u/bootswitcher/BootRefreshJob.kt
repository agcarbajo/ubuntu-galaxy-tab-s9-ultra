package com.gts9u.bootswitcher

import android.app.job.JobInfo
import android.app.job.JobParameters
import android.app.job.JobScheduler
import android.app.job.JobService
import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import java.util.concurrent.Executors

/** A bounded job after unlock/upgrade, with no foreground notification. */
class BootRefreshReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action !in listOf(Intent.ACTION_BOOT_COMPLETED, Intent.ACTION_MY_PACKAGE_REPLACED)) return
        context.getSystemService(JobScheduler::class.java).schedule(
            JobInfo.Builder(110, ComponentName(context, BootRefreshJob::class.java))
                .setMinimumLatency(1000).setOverrideDeadline(60000).build())
    }
}

class BootRefreshJob : JobService() {
    private val executor = Executors.newSingleThreadExecutor()
    override fun onStartJob(params: JobParameters): Boolean {
        executor.execute {
            try {
                if (Root.available()) BootState.read(this)
            } finally {
                jobFinished(params, false)
            }
        }
        return true
    }
    // Never interrupt a backup commit. Boot/app entry points retry if stopped.
    override fun onStopJob(params: JobParameters) = false
    override fun onDestroy() {
        executor.shutdown()
        super.onDestroy()
    }
}
