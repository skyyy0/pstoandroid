plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Optional release signing supplied by CI or a local keystore:
//   gradle assembleRelease -Pstorm.storeFile=/path/keystore.jks \
//       -Pstorm.storePassword=... -Pstorm.keyAlias=... -Pstorm.keyPassword=...
val storeFilePath = providers.gradleProperty("storm.storeFile").orNull
val storePasswordValue = providers.gradleProperty("storm.storePassword").orNull
val keyAliasValue = providers.gradleProperty("storm.keyAlias").orNull
val keyPasswordValue = providers.gradleProperty("storm.keyPassword").orNull

android {
    namespace = "com.sky.stormrev"
    compileSdk = 34
    ndkVersion = "26.1.10909125"

    defaultConfig {
        applicationId = "com.sky.stormrev"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0"

        // Single ABI: every Android device able to run this renderer at 60 fps is
        // arm64. Shipping one ABI halves the native payload in the APK. The CI
        // emulator smoke test overrides it with -Pstorm.abi=x86_64.
        val abiOverride = providers.gradleProperty("storm.abi").orNull
        ndk {
            abiFilters += abiOverride?.split(",")?.map { it.trim() } ?: listOf("arm64-v8a")
        }

        externalNativeBuild {
            cmake {
                arguments += listOf("-DANDROID_STL=c++_static")
                cppFlags += listOf("-std=c++17")
            }
        }
    }

    externalNativeBuild {
        cmake {
            path = file("../../native/CMakeLists.txt")
            version = "3.22.1"
        }
    }

    signingConfigs {
        if (storeFilePath != null && storePasswordValue != null && keyAliasValue != null &&
            keyPasswordValue != null
        ) {
            create("stormRelease") {
                storeFile = file(storeFilePath)
                storePassword = storePasswordValue
                keyAlias = keyAliasValue
                keyPassword = keyPasswordValue
            }
        }
    }

    buildTypes {
        debug {
            isMinifyEnabled = false
            isDebuggable = true
        }
        release {
            // R8 keeps the APK small (no AndroidX, but it still trims Kotlin
            // stdlib and the JNI bridge shims). Debug symbols are dropped from
            // the packaged .so; a symbol archive is optional and disabled.
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
            signingConfig = signingConfigs.findByName("stormRelease")
                ?: signingConfigs.getByName("debug")
            ndk {
                debugSymbolLevel = "none"
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    packaging {
        jniLibs {
            // Native libraries are stored uncompressed and mmap'ed by the
            // loader (no copy at install time). Distribution archives compress
            // them much better than the APK itself could.
            useLegacyPackaging = false
        }
        resources {
            excludes += setOf("META-INF/*.version", "kotlin/**")
        }
    }

    buildFeatures {
        buildConfig = false
        resValues = false
    }
}
