//
// Assertion helpers for consistent error handling
// Replaces assert(false) with exceptions that work in release builds
//

#ifndef STS_LIGHTSPEED_ASSERTION_HELPERS_H
#define STS_LIGHTSPEED_ASSERTION_HELPERS_H

#include <stdexcept>
#include <string>

namespace sts {

// Helper macro for unreachable code paths
#define STS_UNREACHABLE(msg) \
    throw std::runtime_error(std::string("Unreachable code executed: ") + msg)

// Helper for invalid enum values
#define STS_INVALID_ENUM(enum_type, value) \
    throw std::runtime_error(std::string("Invalid " #enum_type " value: ") + std::to_string(static_cast<int>(value)))

// Helper for unimplemented features
#define STS_NOT_IMPLEMENTED(feature) \
    throw std::runtime_error(std::string("Not implemented: ") + feature)

} // namespace sts

#endif // STS_LIGHTSPEED_ASSERTION_HELPERS_H
