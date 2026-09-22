#include "native_timing.hpp"

#include <cassert>
#include <cmath>
#include <cstring>

namespace {

constexpr std::uint64_t kQpcFrequency = 10'000'000;

bool Near(double lhs, double rhs)
{
    return std::fabs(lhs - rhs) < 1e-9;
}

} // namespace

int main()
{
    std::uint64_t previous_qpc = 0;

    // The source is 5 ms after acquisition, but still 3 ms before Present.
    // Acquisition ordering must not reject a valid compositor timestamp.
    const double acquired_ms = 1000.0;
    const auto after_acquire = gfn_timing::RetainSourceTimestamp(
        10'050'000, kQpcFrequency, previous_qpc);
    assert(after_acquire.valid);
    assert(after_acquire.milliseconds > acquired_ms);
    const auto valid_age = gfn_timing::EvaluateSourceAge(after_acquire, 1008.0);
    assert(valid_age.state == gfn_timing::SourceState::Valid);
    assert(Near(valid_age.milliseconds, 3.0));
    assert(std::strcmp(gfn_timing::SourceStateName(valid_age.state), "valid") == 0);

    // A source later than the pre-Present CPU observation remains signed and
    // explicit; it is not clamped and is not replaced with acquisition age.
    const auto future_source = gfn_timing::RetainSourceTimestamp(
        10'100'000, kQpcFrequency, previous_qpc);
    assert(future_source.valid);
    const auto future_age = gfn_timing::EvaluateSourceAge(future_source, 1007.0);
    assert(future_age.state == gfn_timing::SourceState::FutureAtPresent);
    assert(Near(future_age.milliseconds, -3.0));
    assert(std::strcmp(gfn_timing::SourceStateName(future_age.state),
                       "future-at-present") == 0);

    // Missing and non-monotonic timestamps stay invalid.  A rejected sample
    // must not lower the monotonic watermark.
    const auto missing = gfn_timing::RetainSourceTimestamp(
        0, kQpcFrequency, previous_qpc);
    assert(!missing.valid);
    assert(gfn_timing::EvaluateSourceAge(missing, 1010.0).state ==
           gfn_timing::SourceState::Invalid);

    const auto regressed = gfn_timing::RetainSourceTimestamp(
        10'075'000, kQpcFrequency, previous_qpc);
    assert(!regressed.valid);
    assert(previous_qpc == 10'100'000);
    assert(gfn_timing::EvaluateSourceAge(regressed, 1010.0).state ==
           gfn_timing::SourceState::Invalid);

    const auto repeated = gfn_timing::RetainSourceTimestamp(
        10'100'000, kQpcFrequency, previous_qpc);
    assert(!repeated.valid);
    assert(previous_qpc == 10'100'000);

    const auto bad_frequency = gfn_timing::RetainSourceTimestamp(
        10'200'000, 0, previous_qpc);
    assert(!bad_frequency.valid);
    assert(previous_qpc == 10'100'000);

    return 0;
}
