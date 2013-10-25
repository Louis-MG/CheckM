###############################################################################
#
# resultsParser.py - 
#
###############################################################################
#                                                                             #
#    This program is free software: you can redistribute it and/or modify     #
#    it under the terms of the GNU General Public License as published by     #
#    the Free Software Foundation, either version 3 of the License, or        #
#    (at your option) any later version.                                      #
#                                                                             #
#    This program is distributed in the hope that it will be useful,          #
#    but WITHOUT ANY WARRANTY; without even the implied warranty of           #
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the            #
#    GNU General Public License for more details.                             #
#                                                                             #
#    You should have received a copy of the GNU General Public License        #
#    along with this program. If not, see <http://www.gnu.org/licenses/>.     #
#                                                                             #
###############################################################################

from __future__ import print_function

import sys
import os 
import uuid
import shutil
import ast
from collections import defaultdict

import defaultValues 

from hmmer import HMMERRunner, HMMERParser, makeOutputFNs
from hmmerModelParser import HmmModelParser

class ResultsParser():
    """This class does the job of parsing through the txt output from a hmmer run"""
    def __init__(self):
        # make the output file names
        (self.txtOut, self.hmmOut) = makeOutputFNs()
        self.results = {}
        self.models = {}
        self.numQs = 0
    
    def analyseResults(self,
                       directory,
                       hmmFile,
                       eCO=defaultValues.__CHECKM_DEFAULT_E_VAL__,
                       lengthCO=defaultValues.__CHECKM_DEFAULT_LENGTH__,
                       quiet=False,
                       outFile=''
                       ):
        """Parse the results in the output directory"""

        # parse the hmm file itself so we can determine the length of the queries
        model_parser = HmmModelParser(hmmFile)
        for model in model_parser.parse():
            self.models[model.name] = model
        
        self.numQs = len(self.models)
        
        # read bin and scaffold stats into dictionaries
        binStatsFile = os.path.join(directory, defaultValues.__CHECKM_DEFAULT_BIN_STATS_FILE__)
        with open(binStatsFile, 'r') as f:
            s = f.read()
            binStats = ast.literal_eval(s)
        
        scaffoldStatsFile = os.path.join(directory, defaultValues.__CHECKM_DEFAULT_SCAFFOLD_STATS_FILE__)
        with open(scaffoldStatsFile, 'r') as f:
            s = f.read()
            scaffoldStats = ast.literal_eval(s)

        # we expect directory to contain a collection of folders names after the original bins
        for folder in os.listdir(directory): 
            if os.path.isdir(os.path.join(directory, folder)):
                # somewhere to store results
                resultsManager = ResultsManager(folder, lengthCO, eCO, self.models, binStats[folder], scaffoldStats[folder])
                
                # we can now build the hmmer_file_name
                hmmer_file_name = os.path.join(directory, folder, self.txtOut)
                
                # and then we can parse it
                self.parseHmmerResults(hmmer_file_name, resultsManager, quiet)
                self.results[folder] = resultsManager
            
    def parseHmmerResults(self, fileName, storage, quiet):
        """Parse through a hmmer file and see what's what"""
        try:
            with open(fileName, 'r') as hmmer_handle:
                try:
                    HP = HMMERParser(hmmer_handle)
                except:
                    print("Error opening HMM file: ", fileName)
                    raise
                
                while True:
                    hit = HP.next()
                    if hit is None:
                        break
                    storage.addHit(hit)
        except IOError as detail:
            sys.stderr.write(str(detail)+"\n")

    def printHeader(self, outputFormat):
        """Print the NON_VERBOSE header"""
        # keep count of single, double, triple genes etc...
        if outputFormat == 1:
            header = ['Bin Id']
            header += ['Completeness','Contamination']
            header += ['Genome size (bp)', '# scaffolds', '# contigs', 'N50', 'Longest scaffold (bp)', 'Shortest scaffold (bp)']
            header += ['GC', 'GC std (scaffolds > 1Kbps)']
            header += ['Coding density (translation table 11)', '# predicted ORFs']
            header += ['0','1','2','3','4','5+']
            print('\t'.join(header))
            
            if defaultValues.__CHECKM_DEFAULT_MIN_SEQ_LEN_GC_STD__ != 1000:
                print('[Error] Labeling error: GC std (scaffolds > 1Kbps)', sys.exc_info()[0])
                raise
                
        elif outputFormat == 2:
            print('\t'.join(['Bin Id','0','1','2','3','4','5+','Completeness','Contamination']))
        elif outputFormat == 4:
            print('\t', '\t'.join(self.models.keys()))
        elif outputFormat == 5:
            print('Bin Id\tMarker Id\tScaffold Id')
        elif outputFormat == 6:
            print('Bin Id\tMarker Id\tScaffold Ids')
        elif outputFormat == 7:
            print('Bin Id\tScaffold Id\t{Marker Id, Count}')
        elif outputFormat == 8:
            print('Scaffold Id\tBin Id\tLength\tGC\tMarker Ids')
    
    def printSummary(self, outputFormat=1, outFile=''):
        print('  Tabulating results for %d bins in output format %d' % (len(self.results), outputFormat))
        
        # redirect output
        old_stdout = sys.stdout
        if(outFile != ''):
            try:
                # redirect stdout to a file
                sys.stdout = open(outFile, 'w')
            except:
                print("Error diverting stout to file: ", sys.exc_info()[0])
                raise
            
        self.printHeader(outputFormat)  
        for fasta in self.results:
            self.results[fasta].printSummary(outputFormat=outputFormat)
            
        # restore stdout        
        if(outFile != ''):
            try:
                # redirect stdout to a file
                sys.stdout = old_stdout
            except:
                print("Error restoring stdout ", sys.exc_info()[0])
                raise

            print('  Results written to: ' + outFile)

class ResultsManager():
    """Store all the results for a single bin"""
    def __init__(self, name, lengthCO, eCO, models=None, binStats=None, scaffoldStats=None):
        self.name = name
        self.markers = {}
        self.eCO = eCO
        self.lengthCO = lengthCO
        self.models = models
        self.binStats = binStats
        self.scaffoldStats = scaffoldStats
    
    def vetHit(self, hit):
        """See if this hit meets our exacting standards"""
        # we should first check to see if this hit is spurious
        # evalue is the easiest method
        try:
            if self.models[hit.query_name].tc[0] > hit.full_score:
                return False
        except:
            if hit.full_e_value > self.eCO:
                #print "BAD1:", hit.query_name
                return False
        
        # also from the manual, if the bias is significantly large
        # then we shouldn't trust the hit
        if hit.full_bias > hit.full_score*0.5:
            #print "BAD2:", hit.query_name
            return False
        
        # now we can see if we have a long enough match
        alignment_length = float(hit.ali_to - hit.ali_from)
        length_perc = alignment_length/float(hit.query_length)
        if length_perc < self.lengthCO:
            #print "BAD3:", hit.query_name, length_perc, self.lengthCO
            return False
        
        # this is presumably a good hit.
        return True
    
    def addHit(self, hit):
        """process this hit and add to the markers if OK
        
        hit is an instance of simplehmmer.HmmerHit
        """
        if self.vetHit(hit):
            try:
                self.markers[hit.query_name].append(hit)
            except KeyError:
                self.markers[hit.query_name] = [hit]

    def calculateMarkers(self, verbose=False):
        """Returns an object containing summary information 
           When verbose is False a list is returned containing the counts of
           markers for the bin as well as the total completeness and
           contamination.  If the verbose flag is set to true, a dict is
           returned containing each marker as the key and the value as the
           count
        """
        if verbose:
            ret = dict()
            for marker in self.models:
                try:
                    ret[marker] = len(self.markers[marker])
                except KeyError:
                    ret[marker] = 0
            return ret
        else:
            gene_counts = [0]*6
            for marker in self.models:
                # we need to limit it form 0 to 5+
                try:
                    if len(self.markers[marker]) > 5:
                        marker_count = 5
                    else:
                        marker_count = len(self.markers[marker])
                except KeyError:
                    marker_count = 0
                
                gene_counts[marker_count] += 1
            perc_comp = 100*float(len(self.markers))/float(len(self.models))
            perc_cont = 100*float(gene_counts[2] + gene_counts[3] + gene_counts[4] + gene_counts[5])/float(len(self.models))  
            gene_counts.append(perc_comp)
            gene_counts.append(perc_cont)
            return gene_counts

    def printSummary(self, outputFormat=1):
        """print out some information about this bin"""
        if outputFormat == 1:
            data = self.calculateMarkers(verbose=False)
            row = self.name
            row += '\t%0.2f\t%0.2f' % (data[6], data[7])
            row += '\t%d\t%d\t%d\t%d\t%d\t%d' % (self.binStats['Genome size'], self.binStats['# scaffolds'], 
                                             self.binStats['# contigs'], self.binStats['N50'], 
                                             self.binStats['Longest scaffold'], self.binStats['Shortest scaffold'])
            row += '\t%.3f\t%.4f' % (self.binStats['GC'], self.binStats['GC std'])
            row += '\t%.3f\t%d' % (self.binStats['Coding density'], self.binStats['# predicted ORFs'])
            row += '\t' + '\t'.join([str(data[i]) for i in xrange(6)])
            
            print(row)
            
        elif outputFormat == 2:
            data = self.calculateMarkers(verbose=False)
            print("%s\t%s\t%0.2f\t%0.2f" % (self.name,
                                                "\t".join([str(data[i]) for i in range(6)]),
                                                data[6],
                                                data[7]
                                                ))
            
        elif outputFormat == 3:
            data = self.calculateMarkers(verbose=True)
            print("--------------------")
            print(self.name)
            for marker,count in data.iteritems():
                print("%s\t%d" % (marker, count))

            print("TOTAL:\t%d / %d (%0.2f" % (len(self.markers),
                                              len(self.models),
                                              100*float(len(self.markers))/float(len(self.models))
                                              )+"%)")
        elif outputFormat == 4:
            # matrix of bin vs marker counts
            data = self.calculateMarkers(verbose=True)
            columns = self.models.keys()
            print(self.name, end='\t')
            for marker in columns:
                count = 0
                try:
                    count = data[marker]
                except KeyError:
                    pass
                else:
                    print(count, end='\t')
            print()

        elif outputFormat == 5:
            # tabular of bin_id, marker, contig_id
            for marker, hit_list in self.markers.items():
                for hit in hit_list:
                    print(self.name, marker, hit.target_name, sep='\t', end='\n')
                    
        elif outputFormat == 6:
            for marker, hit_list in self.markers.items():
                if len(hit_list) >= 2:
                    print(self.name, marker, sep='\t', end='\t')
                    
                    scaffoldIds = []
                    for hit in hit_list:
                        scaffoldIds.append(hit.target_name)
                        
                    print(','.join(scaffoldIds), end='\n')

        elif outputFormat == 7:
            # tabular - print only contigs that have more than one copy 
            # of the same marker on them
            contigs = defaultdict(dict)
            for marker, hit_list in self.markers.items():
                for hit in hit_list:
                    try:
                        contigs[hit.target_name][marker] += 1
                    except KeyError:
                        contigs[hit.target_name][marker] = 1
            
            for contig_name, marker_counts in contigs.items():
                first_time = True
                for marker_name, marker_count in marker_counts.items():
                    if marker_count > 1:
                        if first_time:
                            first_time = False
                            print(self.name, contig_name, sep='\t', end='\t')
                        print(marker_name, marker_count, sep=',', end='\t')
                if not first_time:
                    print()
                    
        elif outputFormat == 8:
            markersInScaffold = {}
            for marker, hit_list in self.markers.items():
                for hit in hit_list:
                    scaffoldId = hit.target_name[0:hit.target_name.rfind('_')]
                    markersInScaffold[scaffoldId] = markersInScaffold.get(scaffoldId, []) + [marker]
            
            for scaffoldId, data in self.scaffoldStats.iteritems():
                print(scaffoldId, self.name, str(data['length']), str(data['GC']), sep='\t', end='\t')
                
                if scaffoldId in markersInScaffold:
                    markerStr = ','.join(sorted(markersInScaffold[scaffoldId]))
                    print(markerStr, end='\n')
                else:
                    print()
        else:
            print("Unknown output format: ", outputFormat)

class HMMAligner:
    def __init__(self, individualFile=False, includeConsensus=True, outputFormat='PSIBLAST'):
        # make output file names
        self.individualFile = individualFile
        self.includeConsensus = includeConsensus
        self.outputFormat = outputFormat
        (self.txtOut, self.hmmOut) = makeOutputFNs()
        (_, self.hmmAlign) = makeOutputFNs(mode='align')
        
    def makeAlignments(self,
                       directory,
                       hmm,
                       eCO=defaultValues.__CHECKM_DEFAULT_E_VAL__,
                       lengthCO=defaultValues.__CHECKM_DEFAULT_LENGTH__,
                       quiet=False,
                       bestHit=False,
                       generateModelFiles=True
                       ):
        """main wrapper for making hmm alignments
           first parse through the hmm txt and work out all the 
           hits that were made
           we expect directory to contain a collection of folders
           names after the original bins
           we need to use this guy to vet the hits
         """
        models = {}
        model_parser = HmmModelParser(hmm)
        for model in model_parser.parse():
            models[model.name] = model

        resultsManager = ResultsManager('', lengthCO, eCO, models)
        hit_lookup = {}
        unique_hits = {}
        for folder in os.listdir(directory):
            if not os.path.isdir(os.path.join(directory, folder)):
                continue
            
            # we can now build the hmmer_file_name
            hmmer_file_name = os.path.join(directory, folder, self.txtOut)
            hit_lookup[folder] = {}
            with open(hmmer_file_name, 'r') as hmmer_handle:
                try:
                    HP = HMMERParser(hmmer_handle)
                except:
                    print("Error opening HMM file: ", hmmer_file_name)
                    raise
                
                while True:
                    hit = HP.next()
                    if hit is None:
                        break
                    if resultsManager.vetHit(hit): # we only want good hits
                        try:
                            if bestHit:
                                if hit_lookup[folder][hit.query_name][0].full_e_value > hit.full_e_value:
                                    hit_lookup[folder][hit.query_name] = [hit]
                            else:
                                hit_lookup[folder][hit.query_name].append(hit)
                        except KeyError:
                            hit_lookup[folder][hit.query_name] = [hit]
                        try:
                            unique_hits[hit.query_name] += 1
                        except KeyError:
                            unique_hits[hit.query_name] = 1
        
        # make temporary files and write the extracted hmms
        single_hmms = {}
        single_hmm_consensi = {}
        HA = HMMERRunner(mode='align')
        if generateModelFiles:
            HF = HMMERRunner(mode='fetch')
            self.makeAlignmentModels(HF, hmm, unique_hits.keys(), single_hmms, single_hmm_consensi)
        
        # now we need to go through each of the bins and extract the contigs which we need
        for folder in hit_lookup:
            genes_file_name = os.path.join(directory, folder,
                    defaultValues.__CHECKM_DEFAULT_PRODIGAL_AA__) # the seqs to align
            if 0 < len(hit_lookup[folder]):
                self.alignBin(HA, hit_lookup[folder], single_hmms,
                        single_hmm_consensi, genes_file_name, directory, folder)
            elif not quiet:
                print("Skipping alignment for", folder, ": no hits found")
                
        
        # remove the tmp files
        for file_name in single_hmms:
            os.remove(single_hmms[file_name])
        for file_name in single_hmm_consensi:
            os.remove(single_hmm_consensi[file_name])
            
    def alignBin(self, HA, hits, hmms, consensi, fasta,
            directory, folder):
        # hits is a hash of HMM names to hit objects
        """Make alignments for this bin"""
        final_alignment_file = os.path.join(directory, folder, self.hmmAlign) # where to write the whole shebang to
        # a hash of sequence names and sequences
        bin_genes = {}
        with open(fasta, 'r') as fh:
            for cid, seq, _ in self.readfq(fh):
                bin_genes[cid] = seq

        align_tmp_file = os.path.join('/tmp', str(uuid.uuid4()))
        for hit_name in hits:
            align_seq_file = open(os.path.join('/tmp', str(uuid.uuid4())), 'w')

            if self.includeConsensus:
                with open(consensi[hit_name]) as fh:
                    for line in fh:
                        align_seq_file.write(line)

            for hmm_hit in hits[hit_name]:
                start_location = 0
                end_location = len(bin_genes[hmm_hit.target_name])
                
                if hmm_hit.ali_to+100 < end_location:
                    end_location = hmm_hit.ali_to+100 
                
                if hmm_hit.ali_from-100 > start_location:
                    start_location = hmm_hit.ali_from-100 

                align_seq_file.write(">"+hmm_hit.target_name+"\n")
                align_seq_file.write(bin_genes[hmm_hit.target_name][start_location:end_location])
                align_seq_file.write("\n")
            
            align_seq_file.close()
            
            if self.individualFile:
                out_file = os.path.join(directory, folder,hit_name+"_out.align" )
                HA.align(hmms[hit_name], align_seq_file.name, out_file,
                        writeMode='>', outputFormat=self.outputFormat, allcol=False)
                
            else:
                HA.align(hmms[hit_name], align_seq_file.name, align_tmp_file,
                        writeMode='>>', outputFormat=self.outputFormat, allcol=False)
                with open(align_tmp_file, 'a') as fh:
                    fh.write("\n###########################################\n\n")
            
            os.remove(align_seq_file.name)

        if not self.individualFile:
            shutil.copy(align_tmp_file, final_alignment_file)
            os.remove(align_tmp_file)
        
    def makeAlignmentModels(self, HF, hmm, keyz, hmms, consensi):
        """Make a bunch of temporary hmm files which we'll use when aligning"""
        for key in keyz:
            fetch_filename = os.path.join('/tmp', str(uuid.uuid4()))
            emit_filename = os.path.join('/tmp', str(uuid.uuid4()))
            hmms[key] = fetch_filename
            consensi[key] = emit_filename
            HF.fetch(hmm, key, fetch_filename, emit_filename)
            
    def readfq(self, fp): # this is a generator function
        """https://github.com/lh3"""
        last = None # this is a buffer keeping the last unprocessed line
        while True: # mimic closure; is it a bad idea?
            if not last: # the first record or a record following a fastq
                for l in fp: # search for the start of the next record
                    if l[0] in '>@': # fasta/q header line
                        last = l[:-1] # save this line
                        break
            if not last: break
            name, seqs, last = last[1:].split()[0], [], None
            for l in fp: # read the sequence
                if l[0] in '@+>':
                    last = l[:-1]
                    break
                seqs.append(l[:-1])
            if not last or last[0] != '+': # this is a fasta record
                yield name, ''.join(seqs), None # yield a fasta record
                if not last: break
            else: # this is a fastq record
                seq, leng, seqs = ''.join(seqs), 0, []
                for l in fp: # read the quality
                    seqs.append(l[:-1])
                    leng += len(l) - 1
                    if leng >= len(seq): # have read enough quality
                        last = None
                        yield name, seq, ''.join(seqs); # yield a fastq record
                        break
                if last: # reach EOF before reading enough quality
                    yield name, seq, None # yield a fasta record instead
                    break