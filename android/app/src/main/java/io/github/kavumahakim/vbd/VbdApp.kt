package io.github.kavumahakim.vbd

import android.app.Application

class VbdApp : Application() {
    override fun onCreate() {
        super.onCreate()
        SettingsStore.init(this)
        Downloads.init(this)
        Streams.init(this)
        MusicStore.init(this)
        Engine.start(this)
    }
}
