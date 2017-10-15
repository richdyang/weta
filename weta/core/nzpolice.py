import datetime
import hashlib
import math
import random
import re
from itertools import combinations

import numpy
# import scipy.misc
# from scipy import spatial
from Orange.widgets.widget import OWWidget
from nltk.corpus import wordnet
from nltk.wsd import lesk
from pyspark.sql import functions as F
from pyspark.sql.functions import udf, struct
from pyspark.sql.types import IntegerType, StringType, ArrayType, Row

from scipy.optimize import linear_sum_assignment


@udf(returnType=StringType())
def p_locationType(string):
    if "Farm" in string:
        return 1
    if "Residenti" in string:
        return 2
    if "Commerci" in string:
        return 3
    if "Publi" in string:
        return 4
    return "UNKNOWN"


@udf(returnType=IntegerType())
def p_ordinalDate(string):
    start = datetime.datetime.strptime(string.strip(), '%d/%m/%Y')
    return start.toordinal()


@udf(returnType=IntegerType())
def p_time(string):
    hours = int(string.split(":")[0])
    if "PM" in string: hours += 12
    return hours


@udf(returnType=StringType())
def p_entryLocation(string):
    vectors1 = ['PREMISES-REAR', 'PREMISES-FRONT', 'PREMISES-SIDE']
    for x in vectors1:
        if x in string: return x
    return "UNKNOWN"


@udf(returnType=StringType())
def p_entryPoint(string):
    vectors2 = ['POINT OF ENTRY-DOOR', 'POINT OF ENTRY-WINDOW', \
                'POINT OF ENTRY-FENCE', 'POINT OF ENTRY-DOOR: GARAGE']
    vectors3 = ['POE - DOOR', 'POE - WINDOW', 'POE - FENCE', 'POE - GARAGE']
    for x, y in list(zip(vectors2, vectors3)):
        if x in string or y in string: return x
    return "UNKNOWN"


@udf(returnType=IntegerType())
def p_dayOfWeek(string):
    start = datetime.datetime.strptime(string, '%d/%m/%Y')
    return start.weekday()


@udf(returnType=StringType())
def p_northingEasting(string, string2):
    return "%s-%s" % (string, string2)


@udf(returnType=StringType())
def p_methodOfEntry(string):
    if string is None:
        return ''

    narrative = string.split("__________________________________ CREATED BY")[-1]
    if 'NARRATIVE' in narrative or 'CIRCUMSTANCES' in narrative:
        narrative = re.split('NARRATIVE|CIRCUMSTANCES', narrative)[-1]
        narrative = re.split("\*|:", narrative[1:])[0]
    return narrative


# Classifies if the search was messy
@udf(returnType=IntegerType())
def p_messy(string):
    negations = ["NOT ", "NO ", "HAVEN'T", "DIDN'T", 'DIDNT', "HAVENT"]
    messywords = ['MESSY', 'MESSIL', 'RUMMAG', 'TIPPED']
    sentences = [sentence + '.' for sentence in string.split(".") if any(word in sentence for word in messywords)]
    c = 0
    for x in sentences:
        if any(word in x for word in negations):
            c -= 1
        else:
            c += 1
    return 1 if c > 0 else 0


@udf(returnType=StringType())
def p_signature(string):
    if "DEFECA" in string:
        return 1
    if "URINAT" in string:
        return 2
    if "MASTURB" in string:
        return 3
    if "GRAFFIT" in string:
        return 4
    return "UNKNOWN"


@udf(returnType=IntegerType())
def p_propertySecure(string):
    verbs = ['LOCKED', 'FENCED', 'GATED', 'SECURED', 'BOLTED']
    negations = ["NOT ", "NO ", "HAVEN'T", "DIDN'T", 'DIDNT', "HAVENT"]
    c = 0
    sentences = [sentence + '.' for sentence in string.split(".") if any(word in sentence for word in verbs)]
    for x in sentences:
        if any(word in x for word in negations):
            c -= 1
        else:
            c += 1
    return 1 if c > 0 else 0


import nltk
from nltk.parse.stanford import StanfordDependencyParser
import string as string_module

stemmer = nltk.stem.porter.PorterStemmer()
parser = StanfordDependencyParser(
    path_to_models_jar='/Users/Chao/nzpolice/summer/stanford-parser/stanford-parser-3.8.0-models.jar',
    model_path='edu/stanford/nlp/models/lexparser/englishPCFG.ser.gz',
    path_to_jar='/Users/Chao/nzpolice/summer/stanford-parser/stanford-parser.jar',
    java_options='-Xmx1000M',
    verbose=False)
remove_punctuation_map = dict((ord(char), None) for char in string_module.punctuation)
unigram_tagger = nltk.tag.UnigramTagger(nltk.corpus.brown.tagged_sents())
sent_tokenizer = nltk.data.load('tokenizers/punkt/english.pickle')


# For vectorizing text
def stem_tokens(tokens):
    return [stemmer.stem(item) for item in tokens]


# Normalizes text (i.e, tokenizes and then stems words)
def normalize(text):
    return stem_tokens(nltk.word_tokenize(text.lower().translate(remove_punctuation_map)))


@udf(returnType=ArrayType(StringType()))
def p_propertyStolenList(string):
    if "PROPERTY" not in string:
        return []
    property_list = " ".join(
        [re.split(':|_', listing)[0] for listing in re.split("PROPERTY LIST SUMMARY:|PROPERTY STOLEN:", string)])
    text = normalize(property_list)
    tagged = unigram_tagger.tag(text)
    removable = ['modus', 'operandi', 'call', 'with', 'list', 'of', 'location', 'point', 'entry', 'value', 'property'
                                                                                                           'police',
                 'stage', 'name', 'details', 'insured', 'victim', 'address']
    o = []
    for x in tagged:
        if (not (x[1] in ["NN", "NNS"])) or (x[0] in removable):
            pass
        else:
            if not len(x[0]) < 3:
                o.append(x[0])
    return o


@udf(returnType=ArrayType(StringType()))
def p_pullMOTags(string):
    sentences = sent_tokenizer.tokenize(string)
    sentences = [sent.lower().capitalize() for sent in sentences]
    x_relations = []
    for sent in sentences:
        if len(sent.split(" ")) > 100: continue
        try:
            parsed = parser.raw_parse(sent)
            triples = [parse.triples() for parse in parsed]
            selected = [triple for triple in triples[0] if (triple[1] in ("dobj", "nsubjpass"))]
        except:
            continue
        for x in selected:
            x_relations.append(x)
    return x_relations


@udf(returnType=StringType())
def p_narrative_hash(narrative):
    return hashlib.sha224(narrative.encode('utf-8')).hexdigest()


def d_straightLineDistance(x, y):
    xsplit = x.split('-')
    ysplit = y.split('-')
    xN = int(xsplit[0])
    xE = int(xsplit[1])
    yN = int(ysplit[0])
    yE = int(ysplit[1])

    return int(math.sqrt(abs(xE - yE) ** 2 + abs(xN - yN) ** 2))


# 24 hour time difference
def d_timeDifference(x, y):
    diff = abs(int(x) - int(y))
    return min(diff, 24 - diff)


# 7 day week
def d_dayDifference(x, y):
    diff = abs(int(x) - int(y))
    return min(diff, 7 - diff)


# absolute
def d_distance(x, y):
    return abs(int(x) - int(y))


# 1 if same else 0
def d_nominalDistance(x, y):
    if x == 'UNKNOWN' or y == 'UNKNOWN': return -1#'?'
    return 1 if x == y else 0


def d_cosineTFIDF(xvec, yvec):
    if len(xvec) == 0 or len(yvec) == 0: return -1.0#'?'

    # Return cosine similarity
    return (xvec.dot(yvec)/(xvec.norm(2)*yvec.norm(2))).item()#1 - spatial.distance.cosine(xvec, yvec)


# As above, but for 2 grams
def d_cosineTFIDF2(xvec, yvec):
    if len(xvec) == 0 or len(yvec) == 0: return -1.0#'?'

    # Return cosine similarity
    return (xvec.dot(yvec)/(xvec.norm(2)*yvec.norm(2))).item()#1 - spatial.distance.cosine(xvec, yvec)


# As above, but the two grams are parsed verb-noun pairs
def d_cosineMO(xvec, yvec):
    if len(xvec) == 0 or len(yvec) == 0: return -1.0#'?'

    # Return cosine similarity
    return (xvec.dot(yvec)/(xvec.norm(2)*yvec.norm(2))).item()#1 - spatial.distance.cosine(xvec, yvec)


# def d_moSim(x, y):
#     if len(x) == 0 or len(y) == 0: return -1#'?'
#
#     similarity = 0
#     for word in x:
#         for wordy in y:
#             if word == wordy:
#                 similarity += 1 * IDFSPAIRS[word]
#
#     return similarity / ((len(x) + 1) * (len(y) + 1))


# Uses wordnet to discover path similarity between lists
def d_wordNet(x, y):
    if len(x) < 1 or len(y) < 1:
        return -1.0#'?'

    def getUnique(sent, word):
        return lesk(sent, word, pos=wordnet.NOUN)

    # Get word sets
    sensesx = []
    for word in x:
        try:
            sensesx.append(getUnique(x, word))
        except IndexError:
            continue
    sensesy = []
    for word in y:
        try:
            sensesy.append(getUnique(y, word))
        except IndexError:
            continue

    # Form matrix of similarities
    matrix = []
    for wordx in sensesx:
        current = []
        if wordx is None: continue
        for wordy in sensesy:
            if wordy is None: continue
            current.append(wordx.lch_similarity(wordy))
        matrix.append(current)

    # Inverse costs
    max = 0
    for m in matrix:
        for mm in m:
            if mm > max: max = mm
    for m in matrix:
        for mm in m:
            mm = max - mm

    # Find max matches
    cost = numpy.array(matrix)
    row, col = linear_sum_assignment(cost)

    return (cost[row, col].sum() / len(matrix)).item()


# Uses wordnet to discover path similarity between lists
def d_wordNetNormalizedAdditive(x, y):
    if len(x) < 1 or len(y) < 1:
        return -1.0#'?'

    def getUnique(sent, word):
        return lesk(sent, word, pos=wordnet.NOUN)

    # Get word sets
    sensesx = []
    for word in x:
        try:
            sensesx.append(getUnique(x, word))
        except IndexError:
            continue
    sensesy = []
    for word in y:
        try:
            sensesy.append(getUnique(y, word))
        except IndexError:
            continue

    score = 0
    for sx in sensesx:
        for sy in sensesy:
            try:
                score += sx.lch_similarity(sy)
            except AttributeError:
                continue
    return score / (len(sensesx) * len(sensesy))


def d_listSimilarity(x, y):
    if len(x) == 0 or len(y) == 0: return -1.0#'?'

    similarity = 0
    for word in x:
        for wordy in y:
            if word == wordy:
                similarity += 1

    return similarity / ((len(x) + 1) * (len(y) + 1))


###################################################
from collections import OrderedDict

FEATURES_TO_USE = OrderedDict({
    "locationType": ('Location Type', p_locationType, d_nominalDistance),
    'ordinalDate': ('Occurrence Start Date', p_ordinalDate, d_distance),
    'time': ('Occurrence Start Time', p_time, d_timeDifference),
    'entryLocation': ('Narrative', p_entryLocation, d_nominalDistance),
    'entryPoint': ('Narrative', p_entryPoint, d_nominalDistance),
    'dayOfWeek': ('Occurrence Start Date', p_dayOfWeek, d_dayDifference),
    'northingEasting': (('NZTM Location Northing', 'NZTM Location Easting'), p_northingEasting, d_straightLineDistance),

    'methodOfEntry': ('Narrative', p_methodOfEntry, None),  # non final feature
    'messy': ('methodOfEntry', p_messy, d_nominalDistance),
    'signature': ('Narrative', p_signature, d_nominalDistance),
    'propertySecure': ('Narrative', p_propertySecure, d_nominalDistance),
    'propertyStolenWordnet': ('Narrative', p_propertyStolenList, d_wordNet),
    'cosineTFIDF': (None, None, d_cosineTFIDF),
    'cosineTFIDF2': (None, None, d_cosineTFIDF2),
    # 'cosineMO': ('methodOfEntry', p_pullMOTags, d_cosineMO),
    # 'propertyStolenWordNetNA': ('Narrative', p_propertyStolenList, d_wordNetNormalizedAdditive),
    # 'listSimilarity': ('Narrative', p_propertyStolenList, d_listSimilarity),
    # 'moSim': ('methodOfEntry', p_pullMOTags, d_moSim),
})


def nzpolice_preprocess(env, inputs, settings):
    df = inputs['DataFrame']

    df = df.na.fill({'Narrative': ''})
    # df.na.drop(subset=["Narrative"])

    for feature in FEATURES_TO_USE:
        t = FEATURES_TO_USE[feature]
        in_cols = t[0]
        udf_func = t[1]
        if udf_func is not None:
            params = (df[c] for c in in_cols) if isinstance(in_cols, tuple) else [df[in_cols]]
            df = df.withColumn(feature, udf_func(*params))

    df = df.withColumn('group', p_narrative_hash('Narrative'))
    df = df.withColumnRenamed('Master PRN', 'offender')

    return {'DataFrame': df}


def nzpolice_link(env, inputs, settings):
    def set_progress(percentage):
        if env['ui'] is not None:
            widget: OWWidget = env['ui']
            widget.progressBarSet(percentage)

    df = inputs['DataFrame']

    print('Start group offender...')
    # offender -> crimes
    offender_count_list = df.groupby('offender').count().collect()
    offender_count_dict = {row['offender']: row['count'] for row in offender_count_list}

    set_progress(5)

    @udf(returnType=IntegerType())
    def offender_count(offender):
        return offender_count_dict[offender]

    print('associate offence count...')
    df = df.withColumn('count', offender_count('offender'))

    set_progress(10)

    #####################################

    print('Start group reports...')
    grouped_list = df.groupby('group').agg(F.collect_list(struct(*df.columns)).alias('reports')).collect()
    print('group collected')
    groups = {row['group']: row['reports'] for row in grouped_list}

    set_progress(15)

    print('Start statistics for selection...')

    NUM_GROUPS = len(groups)
    NUM_LINKED = 0
    for group in groups:
        length = len(groups[group])
        if length == 1:
            continue
        NUM_LINKED += length*(length-1)-1#scipy.misc.comb(length, 2, exact=True)  # combination

    NUM_TO_SELECT = int(math.ceil(NUM_LINKED / NUM_GROUPS))

    print('%d groups, %d linked, %d select' % (NUM_GROUPS, NUM_LINKED, NUM_TO_SELECT))
    set_progress(20)

    print('Start links combination...')
    links = []
    for group in groups:
        group_weight = 1 / len(groups[group])
        internal_group_links = [t + (group_weight,) for t in combinations(groups[group], 2)]
        external_group_links = list()
        for report in groups[group]:
            random_groups = random.sample([g for g in groups if g != group], NUM_TO_SELECT)
        external_group_links.extend([(report, random.choice(groups[g]), 1.0) for g in random_groups])

        links.extend(internal_group_links)
        links.extend(external_group_links)


    print('Links combination finished: %d' % len(links))
    set_progress(30)

    print('Start links with distance transformation...')
    linked_rows = []
    progress = 0
    for link in links:
        row1 = link[0]
        row2 = link[1]
        row = {feature: FEATURES_TO_USE[feature][2](row1[feature], row2[feature]) for feature in FEATURES_TO_USE if
               FEATURES_TO_USE[feature][2] is not None}
        row['class'] = link[2]
        linked_rows.append(Row(**row))
        progress += 1
        set_progress(30 + progress*60/len(links))

    df = env['sqlContext'].createDataFrame(linked_rows)
    return {'DataFrame': df}
