#-*-coding:utf-8-*-
import weibo_tools
import sqlite3
import time
from datetime import datetime
import traceback
import sys
import os
from STTrans import STTrans
try:
    import ujson as json
except:
    import json

if __name__ == '__main__':
    APP_KEY = '2824743419'
    APP_SECRET = '9c152c876ec980df305d54196539773f'
    CALLBACK_URL = 'http://livep.sinaapp.com/mobile/weibo2/callback.php'
    user_name = '496642325@qq.com'
    user_psw = 'xianchangjia'

    if not os.path.exists("GeoData"):
        os.mkdir("GeoData")
    db=sqlite3.connect("GeoData/weibo_word_base.db")
    try:
        db.execute("create table weibo_text(weibo_id int not null PRIMARY KEY,uid int not null,word varchar(1024) not null,lat float,lng float,time unsigned int)")
    except Exception,e:
        print e
    try:
        db.execute("create table weibo_user_info(uid int not null PRIMARY KEY,info text not null,is_full_info int not null default 0,time unsigned int)")
    except Exception,e:
        print e
    db.commit()
    db.close()

    db=sqlite3.connect("GeoData/GeoPointList.db")
    try:
        db.execute("create table GeoWeiboPoint(id INTEGER PRIMARY KEY,lat float,lng float,last_checktime INT default 0)");
    except Exception,e:
        print e
    db.commit()
    db.close()

    client = weibo_tools.WeiboClient(APP_KEY,APP_SECRET,CALLBACK_URL,user_name,user_psw)

    run_start_time=0
    while True:
        if time.time()-run_start_time<2*60:
            time.sleep(2*60-(time.time()-run_start_time))
        run_start_time=time.time()

        pos_db=sqlite3.connect("GeoData/GeoPointList.db")
        pos_to_record=[]
        pos_cursor=pos_db.cursor()
        pos_cursor.execute('select id,lat,lng,last_checktime from GeoWeiboPoint')
        for line in pos_cursor:
            pos_to_record.append({'id':line[0],'lat':line[1],'lng':line[2],'time':line[3]})
        pos_cursor.close()

        for pos in pos_to_record:
            starttime=pos['time']
            readtime=time.time()
            db=sqlite3.connect("GeoData/weibo_word_base.db")
            total_number=0
            max_id=0
            for page in range(1,11):
                try:
                    place_res=client.place__nearby_timeline(lat= pos['lat'],long=pos['lng'],range=10000,count=50,page=page,offset=1)
                except Exception,e:
                    print e
                    break

                if len(place_res)==0:
                    break
                #print json.dumps(place_res)
                total_number=place_res['total_number']
                statuses=place_res['statuses']
                if len(statuses)==0:
                    break

                not_go_next_page=False
                for line in statuses:
                    if not 'user' in line:
                        continue
                    user=line['user']
                    geo=line['geo']
                    if geo==None:
                        continue
                    if geo['type']=="Point":
                        lat=geo['coordinates'][0]
                        lng=geo['coordinates'][1]
                    else:
                        continue
                    id=line['id']
                    max_id=max(max_id,id)
                    text=line['text']
                    uid=user['id']
                    created_at=line['created_at']
                    #Tue Dec 07 21:18:14 +0800 2010
                    c_time=datetime.strptime(created_at,"%a %b %d %H:%M:%S +0800 %Y")
                    u_time=time.mktime(c_time.timetuple())
                    u_time-=8*3600
                    if id<max_id:
                        not_go_next_page=True
                    db.execute('insert or ignore into weibo_text(weibo_id,uid,word,lat,lng,time) values(?,?,?,?,?,?)',(id,uid,text,lat,lng,u_time))
                    db.execute('insert or ignore into weibo_user_info(uid,info,time) values(?,?,?)',(uid,json.dumps(user),readtime))
                if not_go_next_page:
                    break
            print 'id:%d linecount:%d'%(pos['id'],total_number)
            db.commit()

            if max_id!=0:
                pos_db.execute('update GeoWeiboPoint set last_checktime=? where id=?',(max_id,pos['id']))
                pos_db.commit()