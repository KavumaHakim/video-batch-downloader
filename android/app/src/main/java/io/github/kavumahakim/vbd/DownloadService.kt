package io.github.kavumahakim.vbd

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * Keeps the app alive while the queue has work, so downloads carry on with the
 * screen off or another app open, and shows their progress as a notification.
 */
class DownloadService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var watcher: Job? = null
    private var lastStartId = 0

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        val manager = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL_PROGRESS, "Download progress", NotificationManager.IMPORTANCE_LOW)
            )
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL_DONE, "Finished downloads", NotificationManager.IMPORTANCE_DEFAULT)
            )
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        lastStartId = startId
        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC else 0
        ServiceCompat.startForeground(this, ID_PROGRESS, progressNotification(Downloads.jobs.value), type)
        if (watcher == null) {
            watcher = scope.launch {
                Downloads.jobs.collect { jobs ->
                    if (jobs.none { !it.status.finished }) {
                        finishedNotification(jobs)?.let {
                            getSystemService(NotificationManager::class.java).notify(ID_DONE, it)
                        }
                        ServiceCompat.stopForeground(this@DownloadService, ServiceCompat.STOP_FOREGROUND_REMOVE)
                        stopSelfResult(lastStartId)
                    } else {
                        getSystemService(NotificationManager::class.java).notify(ID_PROGRESS, progressNotification(jobs))
                        delay(700) // notifications are rate limited; no need to redraw more often
                    }
                }
            }
        }
        return START_NOT_STICKY
    }

    // Android 15 caps data-sync services at six hours a day.
    override fun onTimeout(startId: Int, fgsType: Int) {
        stopSelf()
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private fun openApp(): PendingIntent = PendingIntent.getActivity(
        this, 0, Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
    )

    private fun progressNotification(jobs: List<DownloadJob>): Notification {
        val active = jobs.filter { it.status == JobStatus.Downloading || it.status == JobStatus.Processing || it.status == JobStatus.Saving }
        val waiting = jobs.count { it.status == JobStatus.Queued || it.status == JobStatus.Reading || it.status == JobStatus.Starting || it.status == JobStatus.Waiting }
        val done = jobs.count { it.status == JobStatus.Done || it.status == JobStatus.Skipped }
        val first = active.firstOrNull()
        val title = when {
            first != null && active.size == 1 -> first.displayTitle
            active.isNotEmpty() -> "Downloading ${active.size} at once"
            else -> "Getting ready…"
        }
        val text = buildList {
            if (waiting > 0) add("$waiting waiting")
            if (done > 0) add("$done done")
        }.joinToString(" · ")
        return NotificationCompat.Builder(this, CHANNEL_PROGRESS)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle(title)
            .setContentText(text)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(openApp())
            .setProgress(100, ((first?.progress ?: 0f) * 100).toInt(), first == null || first.status != JobStatus.Downloading)
            .build()
    }

    private fun finishedNotification(jobs: List<DownloadJob>): Notification? {
        val done = jobs.count { it.status == JobStatus.Done }
        val failed = jobs.count { it.status == JobStatus.Failed }
        if (done == 0 && failed == 0) return null
        val text = buildList {
            if (done > 0) add("$done saved to ${MediaSaver.LOCATION}")
            if (failed > 0) add("$failed failed")
        }.joinToString(" · ")
        return NotificationCompat.Builder(this, CHANNEL_DONE)
            .setSmallIcon(android.R.drawable.stat_sys_download_done)
            .setContentTitle("Downloads finished")
            .setContentText(text)
            .setAutoCancel(true)
            .setContentIntent(openApp())
            .build()
    }

    companion object {
        private const val CHANNEL_PROGRESS = "progress"
        private const val CHANNEL_DONE = "done"
        private const val ID_PROGRESS = 1
        private const val ID_DONE = 2

        fun start(context: Context) {
            try {
                ContextCompat.startForegroundService(context, Intent(context, DownloadService::class.java))
            } catch (_: Exception) {
                // Started from the background on Android 12+: downloads still run while the app is open.
            }
        }
    }
}
