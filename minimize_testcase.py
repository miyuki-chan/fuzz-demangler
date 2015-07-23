#!/usr/bin/env python

import os, os.path
import re
import sh
import shutil
import sys
import argparse
import resource
import subprocess
from subprocess import PIPE

# This should point to demangler executable
executable_crashing = 'c++filt'

# Try quadratic-time pass
SLOW = False
# Try to replace all non-alphanumeric characters with alphanumeric ones
NON_ALPHANUM = False

def preexec_fn():
    resource.setrlimit(resource.RLIMIT_CPU, (1, 1))
    resource.setrlimit(resource.RLIMIT_RSS, (50000, 50000))

def verify_crash(testcase):
    proc = subprocess.Popen(executable_crashing, preexec_fn=preexec_fn, stdin=PIPE,
                        stdout=PIPE, stderr=PIPE)
    proc.communicate(testcase + '\n')
    return proc.returncode < 0

def verify_crash_z(testcase):
    return verify_crash('_Z' + testcase)

class ReductionPass:
    nonalnum_re = re.compile(r'[^a-zA-Z0-9_]')

    @staticmethod
    def escape_string(s):
        return ReductionPass.nonalnum_re.sub(lambda x: '\\x{:02x}'.format(ord(x.group(0)[0])), s)

    def print_reduction(self, tpl_from, to):
        if not self._quiet:
            str_from = ' | '.join([ ReductionPass.escape_string(x) for x in tpl_from])
            print('Reduced: "{}" -> "{}"'.format(str_from, ReductionPass.escape_string(to)))

    def _test_reduction(self, tpl_from, to):
        res = self._verify(to)
        if res:
            self.print_reduction(tpl_from, to)
        return res

    def __init__(self, quiet, checker):
        self._quiet = quiet
        self._verify = checker

    def print_pass_name(self):
        if not self._quiet:
            print('Pass: ' + self._name)

    def gate(self, testcase):
        return False

    def run(self, testcase):
        return testcase

    def maybe_run(self, testcase):
        if self.gate(testcase):
            self.print_pass_name()
            result = self.run(testcase)
            return ((result != testcase), result)
        return (False, testcase)

    def maybe_loop(self, testcase):
        res = True
        worked = False
        while res:
            if not self.gate(testcase):
                break
            if not worked:
                self.print_pass_name()
            new_test = self.run(testcase)
            res = (new_test != testcase)
            if res:
                worked = True
                testcase = new_test
        return (worked, testcase)

class PassMakeAlnum(ReductionPass):
    """Try to replace all non-alphanumeric characters with alphanumeric ones"""

    def __init__(self, quiet, checker):
        self._name = 'fix non-alphanumeric'
        self._alnum_re = re.compile(r'^[a-zA-Z0-9_]+$')
        ReductionPass.__init__(self, quiet, checker)

    def gate(self, testcase):
        return not bool(self._alnum_re.match(testcase))

    def run(self, testcase):
        for match in ReductionPass.nonalnum_re.finditer(testcase):
            pos = match.start(0)
            for char in ['q', '0', '_']: # q is not used anywhere in current version of grammar
                new_test = testcase[:pos] + char + testcase[pos + 1:]
                if self._test_reduction((testcase,), new_test):
                    testcase = new_test
                    break
        return testcase

class PassShortenIdent(ReductionPass):
    """Try to replace identifiers with one-character ones"""
    def __init__(self, quiet, checker):
        self._name = 'shorten identifiers'
        self._digits_re = re.compile(r'\d{1,7}')
        ReductionPass.__init__(self, quiet, checker)

    def _find_first_ident(self, testcase):
        start_pos = 0
        while True:
            match = self._digits_re.search(testcase, start_pos)
            if not match:
                return None
            end_pos = match.end(0)
            id_len = int(match.group(0))
            if id_len > 1 and end_pos + id_len <= len(testcase):
                return (match.start(0), end_pos + id_len)
            start_pos = end_pos

    def gate(self, testcase):
        return bool(self._find_first_ident(testcase))

    def run(self, testcase):
        head = ''
        tail = testcase
        next_id = ord('A')
        while tail:
            id_range = self._find_first_ident(tail)
            if id_range is None:
                break
            (start_pos, end_pos) = id_range
            try_head = ''.join([head, tail[:start_pos], '1', chr(next_id)])
            new_test = try_head + tail[end_pos:]
            if self._verify(new_test):
                self.print_reduction((head + tail[:start_pos], tail[start_pos:end_pos], tail[end_pos:]), new_test)
                head = try_head
                tail = tail[end_pos:]
                next_id = ord('A') if next_id == ord('Z') else (next_id + 1)
                continue
            head = head + tail[:end_pos]
            tail = tail[end_pos:]
        return head + tail


class PassReplaceBalanced(ReductionPass):
    def __init__(self, quiet, checker):
        self._name = 'replace balanced groups'
        ReductionPass.__init__(self, quiet, checker)

    def gate(self, testcase):
        return 'E' in testcase and len(testcase) > 2 and \
                ('I' in testcase or 'N' in testcase or 'J' in testcase)

    def run(self, testcase):
        head = ''
        tail = testcase
        while tail:
            found = False
            for pos1 in range(0, len(tail) - 2):
                if tail[pos1] in 'JIN':
                    found = True
                    break
            if not found:
                break
            found = False
            for pos2 in range(pos1+1, len(tail)):
                if tail[pos2] != 'E':
                    continue
                new_head = head + tail[:pos1]
                new_test = new_head + '1A' + tail[pos2+1:]
                if self._test_reduction((new_head, tail[pos1:pos2+1], tail[pos2+1:]), new_test):
                    head = new_head + '1A'
                    tail = tail[pos2+1:]
                    found = True
                    break
                if pos2 - pos1 >= 2:
                    new_head = head + tail[:pos1+1]
                    new_test = new_head + 'iE' + tail[pos2:]
                    if self._test_reduction((new_head, tail[pos1+1:pos2], tail[pos2:]), new_test):
                        head = new_head + 'iE'
                        tail = tail[pos2+1:]
                        found = True
                        break
            if not found:
                head = head + tail[:pos1 + 1]
                tail = tail[pos1 + 1:]
        return head + tail

class PassReplaceSubst(ReductionPass):
    def __init__(self, quiet, checker):
        self._name = 'replace substitutions'
        self._sub_re = re.compile(r'S([0-9A-Z]{1,2})_')
        ReductionPass.__init__(self, quiet, checker)

    @staticmethod
    def encode_base36(val):
        if val == 0:
            return ''
        result = ''
        val -= 1
        while True:
            digit = val % 36
            val = val / 36
            result = (chr(digit - 10 + ord('A')) if digit >= 10 else chr(digit + ord('0'))) + result
            if not val:
                break
        return result

    @staticmethod
    def decode_base36(val):
        if val == '':
            return 0
        result = 0
        for c in val:
            if ord(c) >= ord('0') and ord(c) <= ord('9'):
                digit = ord(c) - ord('0')
            else:
                digit = ord(c) - ord('A') + 10
            result = result * 36 + digit
        return result + 1

    def gate(self, testcase):
        return bool(self._sub_re.search(testcase))

    def run(self, testcase):
        head = ''
        tail = testcase
        while tail:
            subst = self._sub_re.search(tail)
            if subst is None:
                break
            try_head = head + tail[:subst.start(0)+1]
            new_tail = tail[subst.end(0):]
            subid = PassReplaceSubst.decode_base36(subst.group(1))
            i = 0
            found = False
            while i < subid:
                new_subst = PassReplaceSubst.encode_base36(i) + '_'
                new_test = try_head + new_subst + new_tail
                if self._test_reduction((try_head, subst.group(1), '_' + new_tail), new_test):
                    head = try_head + new_subst
                    tail = new_tail
                    found = True
                    break
                i = 1 if i == 0 else i * 2
            if not found:
                head = head + tail[:subst.end(0)]
                tail = new_tail
        return head + tail


class PassRemoveTail(ReductionPass):
    def __init__(self, quiet, checker):
        self._name = 'remove tail'
        ReductionPass.__init__(self, quiet, checker)

    def gate(self, testcase):
        return len(testcase) > 1

    def run(self, testcase):
        for pos in range(1, len(testcase)):
            new_test = testcase[:pos]
            if self._test_reduction((new_test, testcase[pos:]), new_test):
                return new_test
        return testcase

class PassRemoveHead(ReductionPass):
    def __init__(self, quiet, checker):
        self._name = 'remove head'
        ReductionPass.__init__(self, quiet, checker)

    def gate(self, testcase):
        return len(testcase) > 1

    def run(self, testcase):
        for pos in range(len(testcase) - 1, 0, -1):
            new_test = testcase[pos:]
            if self._test_reduction((testcase[:pos], new_test), new_test):
                return new_test
        return testcase

class PassRemoveMiddle(ReductionPass):
    def __init__(self, quiet, checker, linear=True):
        self._linear = linear
        self._name = 'remove middle' + (' (linear)' if linear else ' (quadratic)')
        ReductionPass.__init__(self, quiet, checker)

    def gate(self, testcase):
        return len(testcase) > 2

    def run(self, testcase):
        for pos1 in range(0, len(testcase) - 1):
            if self._linear:
                pos2_seq = range(pos1 + 1, min(len(testcase), pos1 + 5))
            else:
                pos2_seq = reversed(range(pos1 + 1, len(testcase)))
            for pos2 in pos2_seq:
                new_test = testcase[:pos1] + testcase[pos2:]
                if self._test_reduction((testcase[:pos1], testcase[pos1:pos2], testcase[pos2:]), new_test):
                    return new_test
        return testcase


class PassPipeline:
    def __init__(self, quiet, checker):
        self.pass_shorten_ident = PassShortenIdent(quiet, checker)
        self.pass_make_alnum = PassMakeAlnum(quiet, checker)
        self.passes_head_tail = [PassRemoveHead(quiet, checker), PassRemoveTail(quiet, checker)]
        self.pass_balanced = PassReplaceBalanced(quiet, checker)
        self.pass_replace_subst = PassReplaceSubst(quiet, checker)
        self.pass_middle_l = PassRemoveMiddle(quiet, checker)
        self.pass_middle_q = PassRemoveMiddle(quiet, checker, False)
        self.cache = None

    def check_and_cache(self, res, testcase):
        if res and self.cache is not None:
            if testcase in self.cache:
                return (None, None)
            self.cache.add(testcase)
        return (res, testcase)

    def run_once(self, pass_inst, testcase):
        (res, testcase) = pass_inst.maybe_run(testcase)
        return self.check_and_cache(res, testcase)

    def run_loop(self, pass_inst, testcase):
        (res, testcase) = pass_inst.maybe_loop(testcase)
        return self.check_and_cache(res, testcase)

    def run(self, testcase, cache):
        self.cache = cache
        if self.cache is not None:
            if testcase in cache:
                return None
            self.cache.add(testcase)

        _, testcase = self.run_once(self.pass_shorten_ident, testcase)
        if testcase is None:
            return None

        while True:
            cur_ind = 0
            num_fails = 0
            while num_fails < len(self.passes_head_tail):
                res, testcase = self.run_once(self.passes_head_tail[cur_ind], testcase)
                if testcase is None:
                    return None
                num_fails = 0 if res else num_fails + 1
                cur_ind = (cur_ind + 1) % len(self.passes_head_tail)
            res, testcase = self.run_loop(self.pass_balanced, testcase)
            if testcase is None:
                return None
            if res:
                continue
            res, testcase = self.run_loop(self.pass_replace_subst, testcase)
            if testcase is None:
                return None
            if res:
                continue
            res, testcase = self.run_loop(self.pass_middle_l, testcase)
            if testcase is None:
                return None
            if SLOW:
                res, testcase = self.run_loop(self.pass_middle_q, testcase)
                if testcase is None:
                    return None
            if not res:
                break
        if NON_ALPHANUM:
            _, testcase = self.run_once(self.pass_make_alnum, testcase)
        return testcase

def reduce_crash(testcase, quiet=False, cache=set()):
    if testcase[:2] == '_Z':
        if not quiet:
            print 'Note: will preserve _Z prefix'
        checker = verify_crash_z
        testcase = testcase[2:]
        pref = '_Z'
    else:
        checker = verify_crash
        pref = ''

    pipeline = PassPipeline(quiet, checker)
    testcase = pipeline.run(testcase, cache)
    if testcase is None:
        return None

    if not quiet:
        print 'Done: "{}{}"'.format(pref, ReductionPass.escape_string(testcase))
    return pref + testcase

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-f', '--file', type=argparse.FileType('r'),
                        help='file to use as input')
    parser.add_argument('symbol', metavar='SYMBOL', nargs='?',
                        help='symbol to demangle')
    res = parser.parse_args()
    if res.symbol is not None:
        testcase = res.symbol
    elif res.file is not None:
        testcase = res.file.read()[:-1]
    else:
        parser.error('no symbol or file specified')
    reduce_crash(testcase)


def main_batch():
    parser = argparse.ArgumentParser()
    parser.add_argument('n', type=int, metavar='N', help='Total number of threads')
    parser.add_argument('m', type=int, metavar='M', help='Thread number (1 - N)')
    args = parser.parse_args()

    cache = set()
    in_f = open('./corpora/filtered2/crashes_ascii.txt', 'rb')
    out_f = open('./corpora/filtered2/crashes_ascii_min_{}.txt'.format(args.m), 'wb')
    cnt = 0
    for (ind, line) in enumerate(in_f):
        if ind % args.n != args.m - 1:
            continue

        line = reduce_crash(line[:-1], True, cache)
        if line is None:
            if ind % 100 == 99:
                print 'Skipped... {}'.format(ind + 1)
        else:
            cnt += 1
            print 'Thread {}. "{}"; {} minimized testcases, position: {}'.format(args.m, ReductionPass.escape_string(line), cnt, ind + 1)
            out_f.write(line + '\n')
    in_f.close()
    out_f.close()

if __name__ == '__main__':
    main()

