// Platform abstraction for locating packaged assets.
#pragma once

#include <cstdint>
#include <fstream>
#include <memory>
#include <string>
#include <vector>

namespace storm {

class AssetSource {
public:
    virtual ~AssetSource() = default;
    virtual bool read(const std::string& path, std::vector<uint8_t>& out) = 0;
};

// Host/desktop implementation: resolves paths against a directory.
class FileAssetSource : public AssetSource {
public:
    explicit FileAssetSource(std::string root) : root_(std::move(root)) {}

    bool read(const std::string& path, std::vector<uint8_t>& out) override {
        std::string full = root_;
        if (!full.empty() && full.back() != '/') full.push_back('/');
        full += path;
        std::ifstream stream(full, std::ios::binary);
        if (!stream) return false;
        stream.seekg(0, std::ios::end);
        const std::streamoff size = stream.tellg();
        if (size <= 0) return false;
        stream.seekg(0, std::ios::beg);
        out.resize(static_cast<size_t>(size));
        stream.read(reinterpret_cast<char*>(out.data()), size);
        return static_cast<bool>(stream);
    }

private:
    std::string root_;
};

// Ordered fallback chain: device storage first, packaged APK assets second.
// Port assets unpacked from the retail game live in the app's own external
// files directory, so they never have to be baked into the APK (which also
// keeps the distributable build free of retail data).
class ChainedAssetSource : public AssetSource {
public:
    void add(std::unique_ptr<AssetSource> source) {
        if (source) sources_.push_back(std::move(source));
    }

    bool empty() const { return sources_.empty(); }

    bool read(const std::string& path, std::vector<uint8_t>& out) override {
        for (const std::unique_ptr<AssetSource>& source : sources_) {
            if (source->read(path, out)) return true;
        }
        out.clear();
        return false;
    }

private:
    std::vector<std::unique_ptr<AssetSource>> sources_;
};

}  // namespace storm
