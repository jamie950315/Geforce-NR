#pragma once

#include <cmath>
#include <cstdint>
#include <limits>

namespace gfn_timing {

enum class SourceState {
    Invalid,
    Valid,
    FutureAtPresent,
};

inline const char* SourceStateName(SourceState state) noexcept
{
    switch (state) {
    case SourceState::Valid:
        return "valid";
    case SourceState::FutureAtPresent:
        return "future-at-present";
    case SourceState::Invalid:
    default:
        return "invalid";
    }
}

struct RetainedSourceTimestamp {
    std::uint64_t qpc = 0;
    double milliseconds = 0.0;
    bool valid = false;
};

// Retain only positive, strictly increasing source timestamps.  Acquisition
// time is deliberately not part of this decision: a WGC compositor timestamp
// can be ahead of the consumer's TryGetNextFrame observation.
inline RetainedSourceTimestamp RetainSourceTimestamp(
    std::uint64_t candidate_qpc,
    std::uint64_t qpc_frequency,
    std::uint64_t& previous_qpc) noexcept
{
    if (candidate_qpc == 0 || qpc_frequency == 0 ||
        candidate_qpc <= previous_qpc)
        return {};

    previous_qpc = candidate_qpc;
    return {
        candidate_qpc,
        static_cast<double>(candidate_qpc) * 1000.0 /
            static_cast<double>(qpc_frequency),
        true,
    };
}

struct SourceAge {
    SourceState state = SourceState::Invalid;
    double milliseconds = std::numeric_limits<double>::quiet_NaN();
};

// Return the signed present-minus-source delta.  Negative values are retained
// and classified instead of being clamped or replaced by acquisition age.
inline SourceAge EvaluateSourceAge(
    const RetainedSourceTimestamp& source,
    double present_call_ms) noexcept
{
    if (!source.valid || !std::isfinite(source.milliseconds) ||
        !std::isfinite(present_call_ms) || present_call_ms <= 0.0)
        return {};

    const double age_ms = present_call_ms - source.milliseconds;
    return {
        age_ms < 0.0 ? SourceState::FutureAtPresent : SourceState::Valid,
        age_ms,
    };
}

} // namespace gfn_timing
