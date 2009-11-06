#!/usr/bin/env python

import wsgiref.handlers

from google.appengine.api.labs import taskqueue
from google.appengine.ext import webapp
from google.appengine.api import users
from google.appengine.ext.webapp import template
from google.appengine.ext import db
from google.appengine.api import urlfetch
from google.appengine.api import mail
from xml.dom import minidom
import time, urllib, os, hashlib
import key

def notify(user, text, title, link=None):
    params = {'text':text,'title':title, 'icon': 'http://feednotifier.appspot.com/favicon.ico'}
    if link:
        params['link'] = link
    urlfetch.fetch('http://api.notify.io/v1/notify/%s?api_key=%s' % (hashlib.md5(user.email()).hexdigest(), key.api_key), method='POST', payload=urllib.urlencode(params))

class Feed(db.Model):
    user = db.UserProperty(auto_current_user_add=True)
    url = db.StringProperty(required=True)
    title = db.StringProperty()
    hub_url = db.StringProperty(required=True)
    created = db.DateTimeProperty(auto_now_add=True)
    updated = db.DateTimeProperty(auto_now=True)

class MainHandler(webapp.RequestHandler):
    def get(self):
        user = users.get_current_user()
        if user:
            logout_url = users.create_logout_url("/")
            feeds = Feed.all().filter('user =', user)
        else:
            login_url = users.create_login_url('/')
        self.response.out.write(template.render('main.html', locals()))
    
    def post(self):
        user = users.get_current_user()
        if self.request.get('id'):
            feed = Feed.get_by_id(int(self.request.get('id')))
            if feed.user == user:
                feed.delete()
                self.redirect('/')
        
        feed_url = self.request.get('url')
        try:
            feed_string = unicode(urlfetch.fetch(feed_url).content.strip(), "utf-8").encode('ascii', 'xmlcharrefreplace')
        except urlfetch.InvalidURLError:
            self.response.out.write("Not a valid URL")
            return
        feed_dom = minidom.parseString(feed_string)
        for link in feed_dom.getElementsByTagName('link'):
            if link.getAttribute('rel') == 'hub':
                # PubSubHubbub enabled feed
                
                hub_url = link.getAttribute('href')
                title = [x.firstChild.data for x in feed_dom.getElementsByTagName('feed')[0].childNodes if x.nodeName == 'title']
                title = title[0] if title else None
                feed = Feed(url=feed_url, hub_url=hub_url, title=title)
                feed.put()
                
                taskqueue.add(url='/subscribe', params={'id': feed.key().id()})
                
                self.redirect('/')
                
        self.response.out.write("Not a feed or not a PubSubHubbub enabled feed")

class SubscribeHandler(webapp.RequestHandler):
    def post(self):
        feed_id = self.request.get('id')
        feed = Feed.get_by_id(int(feed_id))
        if feed:
            params = {
                'hub.mode': 'subscribe',
                'hub.callback': 'http://www.feednotifier.org/notify/%s' % feed_id,
                'hub.topic': feed.url,
                'hub.verify': 'sync',
                'hub.verify_token': feed_id,
            }
            urlfetch.fetch(feed.hub_url, method='POST', payload=urllib.urlencode(params))
        

class NotifyHandler(webapp.RequestHandler):
    def get(self):
        topic = self.request.get('hub.topic')
        feed_id = self.request.get('hub.verify_token')
        feed = Feed.get_by_id(int(feed_id))
        if feed.url == topic:
            notify(feed.user, "Subscribed to updates", feed.title)
            self.response.out.write(self.request.get('hub.challenge'))
        else:
            self.error(404)
    
    def post(self):
        feed_id = self.request.path.split('/')[-1]
        feed = Feed.get_by_id(int(feed_id))
        feed_dom = minidom.parseString(self.request.body.encode('utf-8', 'xmlcharrefreplace'))
        for entry in feed_dom.getElementsByTagName('entry'):
            entry_title = entry.getElementsByTagName('title')[0].firstChild
            entry_title = entry_title.data if entry_title else "???"
            notify(feed.user, entry_title, feed.title or feed.url)

def main():
    application = webapp.WSGIApplication([
        ('/', MainHandler), 
        ('/subscribe', SubscribeHandler),
        ('/notify/.*', NotifyHandler),
        ], debug=True)
    wsgiref.handlers.CGIHandler().run(application)

if __name__ == '__main__':
    main()
