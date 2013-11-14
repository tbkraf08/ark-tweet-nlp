#!/usr/bin/env python
# Author: Toma Kraft
# Date: Nov 11th, 2013

import subprocess
import nltk
import sys
import os
import Queue as ThreadingQueue
from multiprocessing import Process, Queue
import getpass
import datetime
# get home folder
user = getpass.getuser()
cwd = os.getcwd()
cwd = cwd.split('/')

index = 0
for i, loc in enumerate(cwd):
	if loc == user:
		index = i+1
home = '/'.join(cwd[:index])

sys.path.insert(0, os.path.join(home, 'cloaked-gtac/src'))
from twitterOauth import TwitterAuth
from mongo import GeoLookup



def in_dict(check_dict, field, default_val=False):
	if field in check_dict:
		return check_dict[field]
	else:
		return default_val

def removeNonAscii(s): return str("".join(i for i in s if ord(i)<128))


class TwitterNER(Process):
	def __init__(self, inQ, outQ, tagQ, limit=1000):
		Process.__init__(self)
		self.count = 0
		self.limit = limit
		self.inQ = inQ
		self.outQ = outQ
		self.instaQ = tagQ
		
		self.insta_tags = {}
		self.ignore_insta_tags = []
		self.init_ignore_tags()
		self.top_insta_tags = []
		self.num_insta_tags = 15
		
		self.filename = 'ner_tweets.txt'
		self.out_f = open(self.filename, 'wb')
		
		global home
		self.BASE = os.path.join(home, 'ark-tweet-nlp')
		self.JAR_PATH = os.path.join(self.BASE, 'ark-tweet-nlp/target/bin/ark-tweet-nlp-0.3.2.jar')
		self.MODEL_PATH = os.path.join(self.BASE, 'ark-tweet-nlp/src/main/resources/cmu/arktweetnlp/model.ritter_ptb_alldata_fixed.20130723')
		self.command = 'java -Xmx500m -jar '+self.JAR_PATH +' --model '+self.MODEL_PATH+' --output-format conll '+ self.filename
		
		self.geo = GeoLookup()
		
		
		self.KEY_TWITTER = 'twit'
		self.KEY_INSTAGRAM = 'insta'
		
		self.tweets = {}
		self.instagrams = {}
		
	def run(self):
		isAlive = True
		#count = 0 
		while isAlive:
			
			
			item = self.inQ.get()
			#print '[TWINER]', item
			#print
			if item == 'done':
				self.outQ.put('done')
				isAlive = False
				break
				
			if not item:
				continue
			 
			 # source of item
			if not 's_id' in item:
				 continue 
			#count += 1
			#if count % 500 == 0:
			#	print '[TWINER-count]',count
			#	print
			
			if item['s_id'] == self.KEY_TWITTER:
				self.add_tweet(item)
				
			if item['s_id'] == self.KEY_INSTAGRAM:
				#print 'adding instagram'
				self.add_instagram(item)
				
			if self.count%self.limit==0:
				self.after_limit()
	
	def init_ignore_tags(self):
		self.ignore_insta_tags.append('teamfollowback')
		self.ignore_insta_tags.append('follow')
		self.ignore_insta_tags.append('ff')
		self.ignore_insta_tags.append('rt')
		self.ignore_insta_tags.append('retweet')
		self.ignore_insta_tags.append('followback')
		self.ignore_insta_tags.append('iphone')
		self.ignore_insta_tags.append('android')
		self.ignore_insta_tags.append('androidgames')
		self.ignore_insta_tags.append('ipad')
		self.ignore_insta_tags.append('ipadgames')
		self.ignore_insta_tags.append('followforfollow')
		self.ignore_insta_tags.append('followtrick')
		self.ignore_insta_tags.append('followpyramid')
		self.ignore_insta_tags.append('gameinsight')
		self.ignore_insta_tags.append('nowplaying')
		self.ignore_insta_tags.append('np')
		self.ignore_insta_tags.append('storyofmylifefollowparty')
		self.ignore_insta_tags = set(self.ignore_insta_tags)
		
	def insta_track_tags(self, tags):
		tags = [tag.replace('!','') for tag in tags]
		tags = set(tags)
	
		
		for tag in tags:
			if tag in self.ignore_insta_tags: 
				continue
			
			if not tag in self.insta_tags:
				self.insta_tags[tag] = 0
				
			self.insta_tags[tag] += 1

	def calc_top_insta_tags(self):
		self.top_insta_tags = [(v, k) for k, v in self.insta_tags.iteritems()]
		
		self.top_insta_tags.sort()
		self.top_insta_tags.reverse()
		self.top_insta_tags = [x1 for x0, x1 in self.top_insta_tags[:self.num_insta_tags]]	
		
		self.insta_tags = {}
		
		#print self.top_insta_tags
		
	def pass_tags_to_instacrawl(self):
		self.calc_top_insta_tags()
		self.instaQ.put(self.top_insta_tags)
	
	def add_instagram(self, item):
		self.count += 1
		
		_id = in_dict(item, 'id', False)#item[1]
		if not _id:
			return
		
		extracted_text = self.insta_text(item)
		text = ''
		for doc in extracted_text:
			text += doc['text'] + ' '
	
		text = text.replace('\n', '')#item[2].replace('\n','')
		text = text.replace('\t',' ')
		text = text.strip()

		self.out_f.write(_id+'%|% '+text+'\n')
		
		self.tweets[_id] = item
		
	# seperates caption/comments and cleans text
	def insta_text(self, media):
		remove = '<>/'
		KEY_COMMENTS = 'comments'
		KEY_CAPTION = 'caption'
		KEY_LOCATION = 'location'
		KEY_TIMESTAMP = 'created_time'
		KEY_TEXT = 'text'
		KEY_SUB_ID = 'sub_id'
			
		text_comments = []
		
		location = None
		if KEY_LOCATION in media:
			location = media[KEY_LOCATION]
		
		# first get the info from the caption
		if KEY_CAPTION in media:
			cap_doc = {
				"_id":media["id"],
				KEY_LOCATION: location,
				KEY_TEXT: '',
			}
			# get sub id
			if 'id' in media[KEY_CAPTION]:
				cap_doc[KEY_SUB_ID] = media[KEY_CAPTION]['id']
				
			# get timestamp
			if KEY_TIMESTAMP in media[KEY_CAPTION]:
				cap_doc[KEY_TIMESTAMP] = media[KEY_CAPTION][KEY_TIMESTAMP]
				
			# get text
			if KEY_TEXT in media[KEY_CAPTION]:
				cap_doc[KEY_TEXT] = removeNonAscii(media[KEY_CAPTION][KEY_TEXT])
				cap_doc[KEY_TEXT] = ''.join(i for i in cap_doc[KEY_TEXT] if not i in remove)
			
			text_comments.append(cap_doc)
		
		# second get the info from the comments
		if KEY_COMMENTS in media:
			
			for key in media[KEY_COMMENTS]:
				com_doc = {
					"_id":media["id"],
					KEY_SUB_ID: key,
					KEY_LOCATION: location,
					KEY_TEXT: '',
				}
				
				# get timestamp
				if KEY_TIMESTAMP in media[KEY_COMMENTS][key]:
					com_doc[KEY_TIMESTAMP] = media[KEY_COMMENTS][key][KEY_TIMESTAMP]
					
				# get text
				if KEY_TEXT in media[KEY_COMMENTS][key]:
					com_doc[KEY_TEXT] = removeNonAscii(media[KEY_COMMENTS][key][KEY_TEXT])
					com_doc[KEY_TEXT] = ''.join(i for i in com_doc[KEY_TEXT] if not i in remove)
					
				text_comments.append(com_doc)
				
		return text_comments
	
	def add_tweet(self, item):
		if len(item) < 2:
			return 
		
		self.count += 1
		_id = in_dict(item, '_id', False)#item[1]
		
		if not _id:
			return 
		
		text = in_dict(item, 'text', '').replace('\n', '')#item[2].replace('\n','')
		text = text.replace('\t',' ')
		text = text.strip()
		self.out_f.write(_id+'%|% '+text+'\n')
		
		self.tweets[_id] = item

		tags = in_dict(item, 'tags', [])#item[4]
		self.insta_track_tags(tags)

	def after_limit(self):
		self.out_f.close()
		self.loop_output()
		self.out_f = open(self.filename, 'wb')
		self.tweets = {}
		self.instagrams = {}
		
		# need to pass instacrawl the top hashtags
		self.pass_tags_to_instacrawl()
	
	def entity_tokenize(self, text, entities):
		temp_tokens = text.split()
		#print '[START E_TOK]'
		#print '[ETOK]',temp_tokens
		#print '[ENTITIES]', entities
		# if no extracted entities, then just unigram
		if not entities:
			return temp_tokens
		
		
		
		for e in entities:
			if ' ' in e[1]:
				e = e[1].split()
			else:
				e = [e[1]]
			#print '[CUR-E]', e
			i = 0
			while i+len(e) <= len(temp_tokens):
				start = i
				end = i+len(e)
				
				if e == temp_tokens[start:end]:
					del temp_tokens[start:end]
					temp_tokens.insert(start, '_'.join(e))
					break
				i += 1
			
		
		
		#print '[final]', temp_tokens
		#print 
		return temp_tokens
		
	
	def loop_output(self):
		tweet = []
		skip_first_line = False
		results = []
		for output_line in self.run_command(self.command):
		
			
			# first line is just info from the tagger
			if skip_first_line:
				skip_first_line = False
				continue
				
			# if an empty line, then  its the end of a tweet
			if not output_line.strip():
				# only join the words not the POS
				tagged_tweet = ' '.join([t[0] for t in tweet])
			
				tagged_tweet = tagged_tweet.split('%|% ')
				#print '[Tagged_Tweet]',tagged_tweet
				_id = tagged_tweet[0]
				
				if len(tagged_tweet) < 2:
					continue
					
				text = tagged_tweet[1]
				
				entities = self.ne_chunk_tree(nltk.ne_chunk(tweet))
				if entities:
					#text = tagged_tweet[1] 
					results.append((_id, entities))
					self.add_location_to_db(_id, entities)
					
				tokens = self.entity_tokenize(text, entities)
				#print '[TOKENS]', tokens
				#print 
			
				item = in_dict(self.tweets, _id, False)
				if not item:
					continue 
					

				item['tokens'] = tokens
				item['entities'] = entities
				#item += (tokens,)
				self.outQ.put(item)
				#print '[TWINER]',datetime.datetime.now().strftime('%H:%M:%S'),' outQ', item
				#print
				
				#print entities
				#print item
				#print 
				tweet = []
			else:
				line = output_line.split('\t')
				tweet.append((line[0], line[1]))
		
		#return results
		
	def run_command(self, command):
		p = subprocess.Popen(command.split(), stdout=subprocess.PIPE)
		return iter(p.stdout.readline, b'')
	
	
	def ne_chunk_tree(self, tree):
		entities = []
	
	
		#walk through parts of speach hiearchy
		for node in tree:
			entity = ''
	
			#if entity then keep track of it
			if isinstance(node, nltk.tree.Tree):
				
				name = ""
				for value in node:
					name = name + " " + value[0].strip()
				entity = name.strip()
				
	
				#####					 #####
				#	DO LOCATION LOOKUP HERE  # 
				#####					 #####
	
				NERtype = node.pos()[-1][-1]
				if NERtype == 'GPE':
					NERtype = 'LOCATION'
					
				if entity.lower() in self.geo:
					entities.append((NERtype, entity, self.geo[entity.lower()]))
				else:
					entities.append((NERtype, entity))
		return entities

	def add_location_to_db(self, _id, entities):
		item = in_dict(self.tweets, _id, False)
		
		
		
		print '[add]', 
		for e in entities:
			if len(e) >= 3:
				
				info = e[2]
				
				
				# get token geo info
				city = in_dict(info, 'city', '')
				state = in_dict(info, 'region', '')
				country = in_dict(info, 'country', '')
				geo_extracted = in_dict(info, 'geo', '')
		
				date = in_dict(item, 'date', '')
				source_id = in_dict(item, 's_id', '')
		
				## _ID is TWEETID (COULD BE MORE THEN ONE IN DB!)
				##mongo
				#post = {
					#'_id':_id,
					#'b_id':b_id, 
					#'t_id':tweet_id, 
					#'token':token, 
					#'tweet_geo':t_geo, 
					#'user_geo':profile_location, 
					#'geo_extracted':geo_extracted, 
					#'city':city, 
					#'state':state, 
					#'country':country,
					#'cluster_id':'', 
					#'related_clusters':[]
				#}
				#mongo.locations(doc=post)
	
def run_command(command):
    p = subprocess.Popen(command.split(), stdout=subprocess.PIPE)
    return iter(p.stdout.readline, b'')
   
def ne_chunk_tree(tree):
	entities = []


	#walk through parts of speach hiearchy
	for node in tree:
		entity = ''

		#if entity then keep track of it
		if isinstance(node, nltk.tree.Tree):
			
			name = ""
			for value in node:
				name = name + " " + value[0].strip()
			name = name.strip()
			entity = name

			#####					 #####
			#	DO LOCATION LOOKUP HERE  # 
			#####					 #####

			NERtype = node.pos()[-1][-1]
			if NERtype == 'GPE':
				NERtype = 'LOCATION'
				
			entities.append((NERtype, entity))
	return entities

#### EXAMPLE
#tweet = []
#count = -1

#ner = TwitterNER()

## used to get tweetstream
#stream = ThreadingQueue.Queue()
#twitter_auth = TwitterAuth(stream, urlExpanded=True)
#twitter_auth.start()



#out_f = open('new_tweets.txt', 'wb')
#count = 0 
#limit = 100
#while True:
	#count += 1
	#item = stream.get()
	#results = ner.add_tweet(item)
	
	#if results:
		#for i in results:
			#print i[0]
			#print i[1]
			#print
			
#######
			
			
			
			
			
			
			
	#text = item[1].replace('\n','')
	#text = text.replace('\t',' ')
	#out_f.write(text+'\n')
	
	
	#if count%limit==0:
		#out_f.close()
		#for output_line in run_command('java -Xmx500m -jar ./ark-tweet-nlp/target/bin/ark-tweet-nlp-0.3.2.jar --model ./ark-tweet-nlp/src/main/resources/cmu/arktweetnlp/model.ritter_ptb_alldata_fixed.20130723 --output-format conll  ./new_tweets.txt'):
			##print output_line
			#count += 1
			#if count == 0:
				#continue
				
			#if not output_line.strip():
				#print ' '.join([t[0] for t in tweet])
				#print ne_chunk_tree(nltk.ne_chunk(tweet))
				#print 
				#tweet = []
			#else:
				#line = output_line.split('\t')
				#tweet.append((line[0], line[1]))

		#out_f = open('new_tweets.txt', 'wb')
