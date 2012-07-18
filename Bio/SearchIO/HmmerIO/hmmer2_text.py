# Copyright 2012 by Kai Blin.
# This code is part of the Biopython distribution and governed by its
# license.  Please see the LICENSE file that should have been included
# as part of this package.
"""Bio.SearchIO parser for HMMER 2 text output."""

import re
from Bio.Alphabet import generic_protein
from Bio.SearchIO._model import QueryResult, Hit, HSP, HSPFragment

_HSP_ALIGN_LINE = re.compile(r'(\S+):\s+domain (\d+) of (\d+)')

class _HitPlaceholder(object):
    def createHit(self, hsp_list):
        hit = Hit(hsp_list)
        hit.id_ = self.id_
        hit.evalue = self.evalue
        hit.bitscore = self.bitscore
        if self.description:
            hit.description = self.description
        hit.domain_obs_num = self.domain_obs_num
        return hit


class Hmmer2TextParser(object):
    """Iterator for the HMMER 2.0 text output."""

    def __init__(self, handle):
        self.handle = handle
        self.buf = []
        self._meta = self.parse_preamble()

    def __iter__(self):
        for qresult in self.parse_qresult():
            qresult.program = self._meta.get('program')
            qresult.target = self._meta.get('target')
            qresult.version = self._meta.get('version')
            yield qresult

    def read_next(self):
        """Return the next non-empty line, trailing whitespace removed"""
        if len(self.buf) > 0:
            return self.buf.pop()
        self.line = self.handle.readline()
        while self.line and not self.line.strip():
            self.line = self.handle.readline()
        if self.line:
            self.line = self.line.rstrip()
        return self.line

    def push_back(self, line):
        """Un-read a line that should not be parsed yet"""
        self.buf.append(line)

    def parse_key_value(self):
        """Parse key-value pair separated by colon (:)"""
        key, value = self.line.split(':')
        return key.strip(), value.strip()

    def parse_preamble(self):
        """Parse HMMER2 preamble."""
        meta = {}
        state = "GENERIC"
        while self.read_next():
            if state == "GENERIC":
                if self.line.startswith('hmm'):
                    meta['program'] = self.line.split('-')[0].strip()
                elif self.line.startswith('HMMER is'):
                    continue
                elif self.line.startswith('HMMER'):
                    meta['version'] = self.line.split()[1]
                elif self.line.count('-') == 36:
                    state = "OPTIONS"
                continue

            assert state == "OPTIONS"
            assert 'program' in meta

            if self.line.count('-') == 32:
                break

            key, value = self.parse_key_value()
            if meta['program'] == 'hmmsearch':
                if key == 'Sequence database':
                    meta['target'] = value
                    continue
            elif meta['program'] == 'hmmpfam':
                if key == 'HMM file':
                    meta['target'] = value
                    continue
            meta[key] = value

        return meta

    def parse_qresult(self):
        """Parse a HMMER2 query block."""
        while self.read_next():
            if not self.line.startswith('Query'):
                raise StopIteration()
            _, id_ = self.parse_key_value()
            self.qresult = QueryResult(id_)

            description = None

            while self.read_next() and not self.line.startswith('Scores'):
                if self.line.startswith('Accession'):
                    self.qresult.accession = self.parse_key_value()[1]
                if self.line.startswith('Description'):
                    description = self.parse_key_value()[1]

            hit_placeholders = self.parse_hits()
            self.parse_hsps(hit_placeholders)
            self.parse_hsp_alignments()

            while self.read_next() and self.line != '//':
                pass

            if description is not None:
                self.qresult.description = description
            yield self.qresult

    def parse_hits(self):
        """Parse a HMMER2 hit block, beginning with the hit table."""

        hit_placeholders = []
        while self.read_next():
            if self.line.startswith('Parsed'):
                break

            if self.line.startswith('Sequence') or \
               self.line.startswith('Model') or \
               self.line.startswith('-------- '):
                continue

            fields = self.line.split()
            id_ = fields.pop(0)
            domain_obs_num = int(fields.pop())
            evalue = float(fields.pop())
            bitscore = float(fields.pop())
            description = ' '.join(fields).strip()


            hit = _HitPlaceholder()
            hit.id_ = id_
            hit.evalue = evalue
            hit.bitscore = bitscore
            hit.description = description
            hit.domain_obs_num = domain_obs_num
            hit_placeholders.append(hit)

        return hit_placeholders

    def parse_hsps(self, hit_placeholders):
        """Parse a HMMER2 hsp block, beginning with the hsp table."""
        # HSPs may occur in different order than the hits
        # so store Hit objects separately first
        unordered_hits = {}
        while self.read_next():
            if self.line.startswith('Alignments') or \
               self.line.startswith('Histogram') or \
               self.line == '//':
                break
            if self.line.startswith('Model') or \
               self.line.startswith('Sequence') or \
               self.line.startswith('--------'):
                continue

            id_, domain, seq_f, seq_t, seq_compl, hmm_f, hmm_t, hmm_compl, \
            score, evalue = self.line.split()

            frag = HSPFragment(id_, self.qresult.id)
            frag.alphabet = generic_protein
            if self._meta['program'] == 'hmmpfam':
                frag.hit_start = int(hmm_f) - 1
                frag.hit_end = int(hmm_t)
                frag.query_start = int(seq_f) - 1
                frag.query_end = int(seq_t)
            elif self._meta['program'] == 'hmmsearch':
                frag.query_start = int(seq_f) - 1
                frag.query_end = int(seq_t)
                frag.hit_start = int(hmm_f) - 1
                frag.hit_end = int(hmm_t)

            hsp = HSP([frag])
            hsp.evalue = float(evalue)
            hsp.bitscore = float(score)
            hsp.domain_index = int(domain.split('/')[0])
            if self._meta['program'] == 'hmmpfam':
                hsp.hit_endtype = hmm_compl
                hsp.query_endtype = seq_compl
            elif self._meta['program'] == 'hmmsearch':
                hsp.query_endtype = hmm_compl
                hsp.hit_endtype = seq_compl

            if id_ not in unordered_hits:
                placeholder = [ p for p in hit_placeholders if p.id_ == id_][0]
                hit = placeholder.createHit([hsp])
                unordered_hits[id_] = hit
            else:
                hit = unordered_hits[id_]
                hsp.hit_description = hit.description
                hit.append(hsp)

        # The placeholder list is in the correct order, so use that order for
        # the Hit objects in the qresult
        for p in hit_placeholders:
            self.qresult.append(unordered_hits[p.id_])

    def parse_hsp_alignments(self):
        """Parse a HMMER2 HSP alignment block."""
        if not self.line.startswith('Alignments'):
            return

        while self.read_next():
            if self.line == '//' or self.line.startswith('Histogram'):
                break

            match = re.search(_HSP_ALIGN_LINE, self.line)
            if match is None:
                continue

            id_ = match.group(1)
            idx = int(match.group(2))
            num = int(match.group(3))

            hit = self.qresult[id_]
            if hit.domain_obs_num != num:
                continue

            frag = hit[idx-1][0]

            hmmseq = ''
            consensus = ''
            otherseq = ''
            structureseq = ''
            while self.read_next() and self.line.startswith(' '):
                # if there's structure information, parse that
                if self.line[16:18] == 'CS':
                    structureseq += self.line[19:].strip()

                    if not self.read_next():
                        break

                # skip the *-> start marker if it exists
                if self.line[19] == '*':
                    hmmseq += self.line[22:]
                else:
                    hmmseq += self.line[19:]

                if not self.read_next():
                    break
                consensus += self.line[19:].strip()

                if not self.read_next():
                    break
                otherseq += self.line[19:].split()[0].strip()

            self.push_back(self.line)

            # get rid of the end marker
            hmmseq = hmmseq[:-3]

            # if there's structure information, add it to the fragment
            if structureseq:
                frag.aln_annotation['CS'] = structureseq

            if self._meta['program'] == 'hmmpfam':
                frag.hit = hmmseq
                frag.query = otherseq
            else:
                frag.hit = otherseq
                frag.query = hmmseq
