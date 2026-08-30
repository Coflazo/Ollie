// Native hot paths for Ollie.
//
// Scope is deliberately narrow. On this hardware the language model dominates end-to-end
// latency, so C++ here does not make replies appear faster. What it does is make two
// checks cheap enough to run on *every* turn instead of occasionally:
//
//   - the source-overlap guard, which compares each generated reply against every
//     retrieved book passage to catch verbatim reproduction. That is an O(n*m) word-level
//     longest-common-run over a few thousand words per turn.
//   - retrieval fusion, which ranks the candidate pool into a top-k.
//
// Every function has a pure-Python twin in the ollie package, and tests/test_native_parity
// asserts they agree. If this library fails to build or load, Ollie runs identically and
// slightly slower.
//
// Build: ./native/build.sh  (one clang++ invocation, no CMake)

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

#if defined(__APPLE__)
#include <sys/sysctl.h>
#include <sys/types.h>
#elif defined(__linux__)
#include <cstdio>
#endif

namespace {

// Lowercase, strip anything that is not a letter or digit, split on whitespace. Matching
// the Python tokenizer exactly is what makes the parity test meaningful.
std::vector<std::string> tokenize(const char* text) {
    std::vector<std::string> out;
    if (!text) return out;
    std::string current;
    for (const char* p = text; *p; ++p) {
        unsigned char c = static_cast<unsigned char>(*p);
        if (std::isalnum(c)) {
            current.push_back(static_cast<char>(std::tolower(c)));
        } else if (!current.empty()) {
            out.push_back(current);
            current.clear();
        }
    }
    if (!current.empty()) out.push_back(current);
    return out;
}

}  // namespace

extern "C" {

// Physical RAM in bytes, 0 if it cannot be determined.
uint64_t ollie_physical_ram(void) {
#if defined(__APPLE__)
    uint64_t mem = 0;
    size_t len = sizeof(mem);
    int mib[2] = {CTL_HW, HW_MEMSIZE};
    if (sysctl(mib, 2, &mem, &len, nullptr, 0) == 0) return mem;
    return 0;
#elif defined(__linux__)
    FILE* f = std::fopen("/proc/meminfo", "r");
    if (!f) return 0;
    unsigned long kb = 0;
    char label[64];
    if (std::fscanf(f, "%63s %lu", label, &kb) != 2) kb = 0;
    std::fclose(f);
    return static_cast<uint64_t>(kb) * 1024ULL;
#else
    return 0;
#endif
}

// Longest run of consecutive matching words between a reply and a source passage.
//
// This is the copyright guard. A model that has been handed a book passage in its prompt
// will sometimes continue it verbatim; a long contiguous run is the signal. Classic
// dynamic-programming longest-common-substring over word tokens, one rolling row so the
// memory stays flat regardless of passage length.
int32_t ollie_longest_overlap(const char* reply, const char* source) {
    const std::vector<std::string> a = tokenize(reply);
    const std::vector<std::string> b = tokenize(source);
    if (a.empty() || b.empty()) return 0;

    std::vector<int32_t> previous(b.size() + 1, 0);
    std::vector<int32_t> current(b.size() + 1, 0);
    int32_t best = 0;

    for (size_t i = 1; i <= a.size(); ++i) {
        for (size_t j = 1; j <= b.size(); ++j) {
            if (a[i - 1] == b[j - 1]) {
                current[j] = previous[j - 1] + 1;
                if (current[j] > best) best = current[j];
            } else {
                current[j] = 0;
            }
        }
        std::swap(previous, current);
        std::fill(current.begin(), current.end(), 0);
    }
    return best;
}

// Fuse retrieval signals and return the indices of the top k, best first.
//
// Mirrors retrieve.search_corpus's scoring exactly:
//   score = 0.72*lexical + 0.20*(category prior hit) + 0.08*min(1, length/1800)
int32_t ollie_rank(const double* lexical, const int32_t* category_hit,
                   const int32_t* lengths, int32_t n, int32_t k, int32_t* out_indices) {
    if (n <= 0 || k <= 0 || !lexical || !category_hit || !lengths || !out_indices) {
        return 0;
    }

    std::vector<std::pair<double, int32_t>> scored;
    scored.reserve(static_cast<size_t>(n));
    for (int32_t i = 0; i < n; ++i) {
        double length_bonus = std::min(1.0, static_cast<double>(lengths[i]) / 1800.0);
        double score = 0.72 * lexical[i]
                     + 0.20 * (category_hit[i] ? 1.0 : 0.0)
                     + 0.08 * length_bonus;
        scored.emplace_back(score, i);
    }

    const int32_t take = std::min(k, n);
    // Ties break toward the lower index, which is what Python's stable sort does.
    std::partial_sort(scored.begin(), scored.begin() + take, scored.end(),
                      [](const std::pair<double, int32_t>& x,
                         const std::pair<double, int32_t>& y) {
                          if (x.first != y.first) return x.first > y.first;
                          return x.second < y.second;
                      });

    for (int32_t i = 0; i < take; ++i) out_indices[i] = scored[static_cast<size_t>(i)].second;
    return take;
}

// Reported by the health endpoint so the UI can say which path is live.
const char* ollie_version(void) { return "ollie_native 0.1.0"; }

}  // extern "C"
