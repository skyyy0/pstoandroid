# JNI entry points are resolved by name at link time, but R8 also renames the
# Kotlin shell classes. Keep the bridge and the activity that the manifest names.
-keep class com.sky.stormrev.NativeBridge { *; }
-keep class com.sky.stormrev.MainActivity { *; }
-keep class com.sky.stormrev.StormGLSurfaceView { *; }
-keep class com.sky.stormrev.TouchOverlayView { *; }
-keep class com.sky.stormrev.ThermalMonitor { *; }
-dontwarn android.**
