// Native hot paths for Ollie.
//
// Scope is narrow on purpose. On this hardware the language model dominates end-to-end
// latency, so nothing here makes a reply appear faster. What it does is make the checks
// that guard every reply cheap enough to run on every reply rather than occasionally:
//
//   - the source-overlap guard, which compares each generated reply against every
//     retrieved passage to catch verbatim reproduction of a copyrighted book;
//   - retrieval fusion, which ranks a candidate pool into a top-k;
//   - memory scoring, which ranks the user's own records against the current message.
//
// Every function has a pure-Python twin in native/loader.py, and
// tests/test_native_parity.py runs both over randomised input and compares. The Python
// twins are written as the obviously-correct reference; the versions here are allowed to
// be clever because that test is what proves they still agree. If the library fails to
// build or load, Ollie behaves identically and runs slower.
//
// Build: ./native/build.sh  (one clang++ invocation, no CMake)

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <cmath>
#include <cstring>
#include <string>
#include <unordered_map>
#include <vector>

#if defined(__APPLE__)
#include <sys/sysctl.h>
#include <sys/types.h>
#elif defined(__linux__)
#include <cstdio>
#endif

namespace {

// Lowercase, drop anything that is not alphanumeric, split on the gaps. Matching the
// Python tokenizer exactly is what makes the parity test meaningful.
std::vector<std::string> tokenize(const char* text) {
    std::vector<std::string> out;
    if (!text) return out;
    std::string current;
    for (const char* p = text; *p; ++p) {
        unsigned char c = static_cast<unsigned char>(*p);
        if (std::isalnum(c)) {
            current.push_back(static_cast<char>(std::tolower(c)));
        } else if (!current.empty()) {
            out.push_back(std::move(current));
            current.clear();
        }
    }
    if (!current.empty()) out.push_back(std::move(current));
    return out;
}

// Map each distinct word to a small integer once, so the inner loops compare ints rather
// than strings. Tokens are compared by identity from here on.
std::pair<std::vector<uint32_t>, std::vector<uint32_t>> intern(
    const std::vector<std::string>& a, const std::vector<std::string>& b) {
    std::unordered_map<std::string, uint32_t> ids;
    ids.reserve(a.size() + b.size());
    auto encode = [&ids](const std::vector<std::string>& words) {
        std::vector<uint32_t> out;
        out.reserve(words.size());
        for (const auto& w : words) {
            auto [it, inserted] = ids.emplace(w, static_cast<uint32_t>(ids.size()));
            out.push_back(it->second);
        }
        return out;
    };
    auto ea = encode(a);
    auto eb = encode(b);
    return {std::move(ea), std::move(eb)};
}

constexpr uint64_t kMod = (1ULL << 61) - 1;  // Mersenne prime: mulmod without __int128 pain
constexpr uint64_t kBase = 1000003;

inline uint64_t mulmod(uint64_t x, uint64_t y) {
    __uint128_t z = static_cast<__uint128_t>(x) * y;
    uint64_t lo = static_cast<uint64_t>(z & kMod);
    uint64_t hi = static_cast<uint64_t>(z >> 61);
    uint64_t r = lo + hi;
    return r >= kMod ? r - kMod : r;
}

// Is there a run of exactly `len` consecutive tokens shared by both sequences?
//
// Rolling hash over every window of `a`, then probe every window of `b`. A hash hit is
// verified token by token before it counts, so a collision can cost time but can never
// produce a wrong answer. That matters: this guard is the thing standing between the
// product and reproducing a copyrighted book verbatim.
bool has_common_run(const std::vector<uint32_t>& a, const std::vector<uint32_t>& b,
                    size_t len) {
    if (len == 0) return true;
    if (len > a.size() || len > b.size()) return false;

    uint64_t power = 1;
    for (size_t i = 0; i + 1 < len; ++i) power = mulmod(power, kBase);

    auto roll = [&](const std::vector<uint32_t>& seq, size_t start, uint64_t previous,
                    bool first) {
        if (first) {
            uint64_t h = 0;
            for (size_t i = 0; i < len; ++i)
                h = (mulmod(h, kBase) + seq[start + i] + 1) % kMod;
            return h;
        }
        uint64_t drop = mulmod(seq[start - 1] + 1, power);
        uint64_t h = (previous + kMod - drop) % kMod;
        return (mulmod(h, kBase) + seq[start + len - 1] + 1) % kMod;
    };

    std::unordered_multimap<uint64_t, size_t> windows;
    windows.reserve(a.size() - len + 1);
    uint64_t h = 0;
    for (size_t i = 0; i + len <= a.size(); ++i) {
        h = roll(a, i, h, i == 0);
        windows.emplace(h, i);
    }

    uint64_t g = 0;
    for (size_t j = 0; j + len <= b.size(); ++j) {
        g = roll(b, j, g, j == 0);
        auto range = windows.equal_range(g);
        for (auto it = range.first; it != range.second; ++it) {
            if (std::equal(a.begin() + it->second, a.begin() + it->second + len,
                           b.begin() + j)) {
                return true;
            }
        }
    }
    return false;
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
// This is the copyright guard. A model handed a book passage in its prompt will sometimes
// continue it verbatim, and a long contiguous run is the signal.
//
// The obvious implementation is the longest-common-substring dynamic program, which is
// O(n*m) time and O(m) space. That is what the Python twin does, because it is easy to
// read and easy to trust. Here we binary search the answer instead: the predicate "a run
// of length L exists" is monotone in L, so O(log n) rolling-hash passes settle it in
// O((n + m) log n) expected time with no large allocation. Over a 120-word reply against
// a 900-word passage that is roughly two orders of magnitude fewer operations, which is
// what lets this run against every retrieved passage on every single turn.
int32_t ollie_longest_overlap(const char* reply, const char* source) {
    const std::vector<std::string> wa = tokenize(reply);
    const std::vector<std::string> wb = tokenize(source);
    if (wa.empty() || wb.empty()) return 0;

    auto [a, b] = intern(wa, wb);

    size_t lo = 0;                              // known achievable
    size_t hi = std::min(a.size(), b.size());   // known upper bound
    while (lo < hi) {
        size_t mid = lo + (hi - lo + 1) / 2;
        if (has_common_run(a, b, mid)) {
            lo = mid;
        } else {
            hi = mid - 1;
        }
    }
    return static_cast<int32_t>(lo);
}

// Fuse retrieval signals and return the indices of the top k, best first.
//
// Mirrors retrieve.search_corpus's scoring exactly:
//   score = 0.72*lexical + 0.20*(category prior hit) + 0.08*min(1, length/1800)
//
// partial_sort rather than a full sort: the caller wants three or four passages out of a
// pool of forty, and there is no reason to order the rest.
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
    // Ties break toward the lower index, matching Python's stable sort.
    std::partial_sort(scored.begin(), scored.begin() + take, scored.end(),
                      [](const std::pair<double, int32_t>& x,
                         const std::pair<double, int32_t>& y) {
                          if (x.first != y.first) return x.first > y.first;
                          return x.second < y.second;
                      });

    for (int32_t i = 0; i < take; ++i)
        out_indices[i] = scored[static_cast<size_t>(i)].second;
    return take;
}

// Score the user's own memory records against the current message.
//
// Runs once per turn over every stored memory, so the cost grows for as long as someone
// keeps using the product.
//
//   score = 0.34*lexical + 0.24*(importance/5) + 0.16*confidence
//         + 0.12*recency  + 0.14*locked  + 0.15*commitment
//         - sensitivity and confirmation penalties
//
// The term matching happens here rather than in the caller, and that is the whole reason
// this function is worth crossing the language boundary for. An earlier version took a
// precomputed overlap count and did only the arithmetic; measured against the Python twin
// it was consistently *slower*, because marshalling eight arrays through ctypes costs more
// than the multiply-adds it saved. Doing the substring search too, which is 20 terms
// against every record, is enough work to pay for the crossing.
//
// Layout, chosen to make that crossing one call with four arguments instead of ten:
//   terms  : query terms, newline separated, already lowercased by the caller
//   texts  : each record's search surface, newline separated, same order as the numbers
//   ints   : 5 per record - importance, locked, is_commitment, sensitivity, needs_confirm
//            (sensitivity: 0 normal, 1 personal, 2 special category)
//   doubles: 2 per record - confidence, age in days
int32_t ollie_score_memories(const char* terms, const char* texts, const int32_t* ints,
                             const double* doubles, int32_t n, double* out_scores) {
    if (n <= 0 || !out_scores || !ints || !doubles) return 0;

    auto split = [](const char* blob) {
        std::vector<std::string> out;
        if (!blob) return out;
        const char* start = blob;
        for (const char* p = blob;; ++p) {
            if (*p == '\n' || *p == '\0') {
                out.emplace_back(start, static_cast<size_t>(p - start));
                if (*p == '\0') break;
                start = p + 1;
            }
        }
        return out;
    };

    const std::vector<std::string> term_list = split(terms);
    const std::vector<std::string> text_list = split(texts);

    for (int32_t i = 0; i < n; ++i) {
        int32_t overlap = 0;
        if (static_cast<size_t>(i) < text_list.size()) {
            const std::string& haystack = text_list[static_cast<size_t>(i)];
            for (const auto& t : term_list) {
                if (!t.empty() && haystack.find(t) != std::string::npos) ++overlap;
            }
        }

        const int32_t* row = ints + static_cast<size_t>(i) * 5;
        const double* drow = doubles + static_cast<size_t>(i) * 2;

        double lexical = std::min(1.0, static_cast<double>(overlap) / 3.0);
        double age = drow[1] < 0.0 ? 0.0 : drow[1];
        double recency = 1.0 / (1.0 + std::log1p(age));

        double score = 0.34 * lexical
                     + 0.24 * (static_cast<double>(row[0]) / 5.0)
                     + 0.16 * drow[0]
                     + 0.12 * recency
                     + (row[1] ? 0.14 : 0.0)
                     + (row[2] ? 0.15 : 0.0);

        if (row[3] == 2) score -= 0.30;
        else if (row[3] == 1) score -= 0.05;
        if (row[4]) score -= 0.10;

        out_scores[i] = score;
    }
    return n;
}

const char* ollie_version(void) { return "ollie_native 0.2.0"; }

}  // extern "C"
