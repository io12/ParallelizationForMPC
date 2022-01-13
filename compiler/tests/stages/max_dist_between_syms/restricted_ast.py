def max_dist_between_syms(Seq: shared[list[std::uint32_t]], N: plaintext[std::uint32_t], Sym: shared[std::uint32_t]):
    max_dist = 0
    current_dist = 0
    for i: plaintext[int] in range(0, N):
        if not (Seq[i] == Sym):
            current_dist = (current_dist + 1)
        else:
            current_dist = 0
        if (current_dist > max_dist):
            max_dist = current_dist
    return max_dist
