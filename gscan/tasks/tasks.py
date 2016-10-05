#!/usr/bin/python
# -*- coding: UTF-8 -*-

from __future__ import absolute_import

from gscan.tasks.celery import app
from gscan.tasks.control import Console
from celery import group

from gscan.models import *
from gscan.tasks.masscan.xmlparse import Xmlparse
from gscan.tasks.subdomain.httprequest import http_request

import dns.resolver
import time
import subprocess
import os

"""

ManageTask Module

"""


@app.task(bind=True, default_retry_delay=30, max_retries=3)
@app.task
def manage_task(task_id):
	IP_LIST[task_id] = []

	while True:
		task = Tasks.objects.get(taskid = task_id)
		if task.domain == 'pend':
			sub_sum, next_sum = load_subname('sum')
			subdomain_start.delay(task_id, task.target)
			Tasks.objects.filter(taskid = task_id).update(domain='start')
		elif task.domain == 'end':
			if task.service == 'pend':
				masscan_pend(task_id)
			elif task.service == 'start':
				masscan_start(task_id)
			elif task.service == 'http':
				service_list = Service.objects.filter(taskid=task_id).order_by('ip','port')
				chain = (group(service_http.s(task_id=task_id, ip=service.ip, port=service.port) for service in service_list) | 
						service_finish.s(task_id=task_id))
				chain()
				Tasks.objects.filter(taskid = task_id).update(service='end')
		if task.weakfile == 'start':
			weakfile_start(task_id)
			break
		print 'ManageTask ...'
		time.sleep(10)
			



"""

SubDomain Scan Module

"""
IP_LIST = {}
BLACK_LIST = []
next_sub_list = []

@app.task
def subdomain_start(task_id, target):
	global next_sub_list
	sub_list, next_sub_list = load_subname('list')
	chain = (group(subdomain_task.s(task_id=task_id, domain=sub + '.' + target) for sub in sub_list) |
			subdomain_finish.s(task_id=task_id,module='sub'))
	chain()
	"""
	for sub in sub_list:
		subdomain_task.apply_async(args=[task_id, sub + '.' + target, 'sub'], queue=task_id)
	Console().add_consumer(task_id)"""


@app.task
def subdomain_finish(results,task_id,module):
	if module == 'http':
		Tasks.objects.filter(taskid = task_id).update(domain='end')
		return
	del_list = []
	for _ip in IP_LIST[task_id]:
		if (IP_LIST[task_id].count(_ip) == 11) and (_ip not in del_list):
			del_list.append(_ip)
			Domain.objects.filter(taskid=task_id, ip=_ip).delete()
	if module == 'sub':
		next_list = []
		domains = Domain.objects.filter(taskid = task_id).all()
		for domain in domains:
			for next_sub in next_sub_list:
				next_list.append((domain.target,next_sub))
		chain = (group(subdomain_task.s(task_id=task_id, domain=sub + '.' + target) for target,sub in next_list) |
				subdomain_finish.s(task_id=task_id,module='next'))
		chain()
	elif module == 'next':
		del IP_LIST[task_id]
		domains = Domain.objects.filter(taskid = task_id).all()
		chain = (group(subdomain_http.s(task_id=task_id, domain=domain.target) for domain in domains) |
				subdomain_finish.s(task_id=task_id,module='http'))
		chain()
		

def load_subname(choose):
	sub_list = []
	nextsub_list = []
	sub_sum = 0
	next_sum = 0
	sub_file = 'gscan/tasks/subdomain/dict/subnames.txt'
	with open(sub_file) as f:
		for line in f:
			sub_sum += 1
			sub_list.append(line.strip())

	next_sub_file = 'gscan/tasks/subdomain/dict/next_sub.txt'
	with open(next_sub_file) as f:
		for line in f:
			next_sum += 1
			nextsub_list.append(line.strip())
	if choose == 'list':
		return sub_list, nextsub_list
	elif choose == 'sum':
		return sub_sum, next_sum

def subdomain_save(task_id, target, ip):
	new_subdomain = Domain(
					taskid = task_id,
					target = target,
					ip = ip,
					status = '',
					)
	new_subdomain.save()
	

@app.task
def subdomain_http(task_id,domain):
	status = http_request('http://'+domain)
	Domain.objects.filter(taskid = task_id, target = domain).update(status=status)


@app.task
def subdomain_task(task_id,domain):
	global IP_LIST, BLACK_LIST
	ip = ''

	try:
		ns = dns.resolver.query(domain)
		if ns:
			for _ in ns:
				ip = ip + _.address + ','
		ip = ip[0:-1]
		if len(IP_LIST[task_id]) == 0:
			IP_LIST[task_id].append(ip)
		else:
			if ip not in IP_LIST[task_id]:
				IP_LIST[task_id].append(ip)
			elif IP_LIST[task_id].count(ip) <= 10:
				IP_LIST[task_id].append(ip)
			elif IP_LIST[task_id].count(ip) > 10:
				return {'task_id': task_id, 'url': domain, 'status': False, 'ip': ''}
		subdomain_save(task_id, domain, ip)
		return {'task_id': task_id, 'url': domain, 'status': True, 'ip': ip}
	except Exception, e:
		return {'task_id': task_id, 'url': domain, 'status': False, 'ip': ''}


"""

Masscan Scan Module

"""

def masscan_pend(task_id):
	ips_list = []
	deal_list = []
	mastmp = []
	domains = Domain.objects.filter(taskid=task_id).all()
	for domain in domains:
		if ',' in domain.ip:
			for _ in domain.ip.split(','):
				ips_list.append(_)	
		else:
			ips_list.append(domain.ip)
	for ip in ips_list:
		ret = ip.split('.')
		if not len(ret) == 4:
			continue
		if ret[0] == '127.0.0.1':
			continue
		if ret[0] == '10':
			continue
		if ret[0] == '172' and 16 <= int(ret[1]) <= 32:
			continue
		#if ret[0] == '192' and ret[1] == '168':
		#	continue
		deal_ip = ret[0] + '.' + ret[1] + '.' + ret[2] + '.0'
		if deal_list.count(deal_ip) == 0:
			deal_list.append(deal_ip)
	for ip in deal_list:
		mastmp.append(MasTmp(taskid = task_id, ip = ip, status = '0'))
	MasTmp.objects.bulk_create(mastmp)
	Tasks.objects.filter(taskid = task_id).update(service='start')
	return deal_list


def masscan_start(task_id):
	mastask = MasTmp.objects.filter(taskid = task_id).all()
	right = 0
	for mas in mastask:
		if mas.status == '2':
			right = 1
			continue
		elif mas.status == '1':
			right = 0
			masscan_go(mas.taskid, mas.ip)
			break
		elif mas.status == '0':
			right = 0
			masscan_task.delay(task_id, mas.ip)
			break
	if right == 1:
		Tasks.objects.filter(taskid = task_id).update(service='http')
		service_plugin(task_id)

			
def masscan_go(taskid, ip):
	service_rs = []
	path = os.getcwd()
	rs_xml = path + '/gscan/tasks/masscanxml/' + taskid + '_' + ip + '.xml'
	if '<finished' in open(rs_xml).read():
		rs_list = Xmlparse(rs_xml).xmlparse()
		seviceport = []
		plugin_list = Plugins.objects.filter(type = 'Service').all()
		for p in plugin_list:
			for rs in rs_list:
				if rs[1] in p.port.split(','):
					plugin = Plugins.objects.get(port=p.port)
					plugin_path = plugin.path
				else:
				    plugin_path = ''
			service_rs.append(Service(taskid = taskid, ip = rs[0], port = rs[1], target = '', pluginpath= plugin_path, status = ''))
		Service.objects.bulk_create(service_rs)
		MasTmp.objects.filter(taskid = taskid, ip = ip).update(status='2')

@app.task
def service_http(task_id, ip, port):
	if port not in ['21','22','1433','3306','3389']:
		url = 'http://' + ip + ':' + port
		status = http_request(url)
		return {'taskid': task_id,'ip': ip,'port': port,'status': status}
	return {'taskid': task_id,'ip': ip,'port': port,'status': '0'}


@app.task
def service_finish(results,task_id):
	if not isinstance(results, list):
		results = [results]
	for res in results:
		Service.objects.filter(taskid = res['taskid'], ip = res['ip'], port = res['port']).update(status=res['status'])
	Tasks.objects.filter(taskid = task_id).update(weakfile='start')



@app.task
def masscan_task(task_id, ip):
	path = os.getcwd()
	run_script_path = '/root/masscan/bin'
	rs_xml = path + '/gscan/tasks/masscanxml/' + task_id + '_' + ip + '.xml'
	task = Tasks.objects.get(taskid = task_id)
	config = Config.objects.get(id = task.config)
	#cmdline = './masscan %s/24 -p%s -oX %s' % (ip, config.ports, rs_xml)
	cmdline = 'masscan %s/24 -p%s -oX %s' % (ip, config.ports, rs_xml)#kali
	MasTmp.objects.filter(taskid = task_id, ip = ip).update(status='1')
	#subprocess.Popen(cmdline,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=run_script_path)
	subprocess.Popen(cmdline,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)#cwd=run_script_path) kali!!


"""

Weakfile Scan Module

"""

def weakfile_start(task_id):
	http_list = Service.objects.filter(taskid=task_id).exclude(status=0).order_by('ip','port')
	chain = (group(weakfile_scan.s(task_id=task_id, target=http.ip + ':' + http.port) for http in http_list)|
			weakfile_finish.s(task_id=task_id))
	chain()
	
@app.task
def weakfile_scan(task_id,target):
	weak_rs = []
	results = getattr(__import__('gscan.tasks.weakfile.weakfile',fromlist=["WeakfileScan"]), "WeakfileScan")(task_id, target).scan()
	if not isinstance(results, list):
		results = [results]
	for res in results:
		weak_rs.append(Weakfile(taskid = res['taskid'], target = res['target'], weakfile = res['file'], status = res['status'], plugid = 0, pluginpath = res['plugin'], data = ''))
	Weakfile.objects.bulk_create(weak_rs)	
	return results


@app.task
def weakfile_finish(results,task_id):
	web_plugin(task_id)


"""

Plugins Scan Module

"""

def service_plugin(task_id):
	service_list = Service.objects.filter(taskid=task_id).exclude(pluginpath='')
	group(plugin_scan.s(task_id=task_id, target=service.ip, script=service.pluginpath, scantype='service') for service in service_list)()


def web_plugin(task_id):
	file_list = Weakfile.objects.filter(taskid=task_id).exclude(pluginpath='')
	print len(file_list)
	if len(file_list) > 0:
		group(plugin_scan.s(task_id=task_id, target=webfile.weakfile, script=webfile.pluginpath, scantype='web') for webfile in file_list)()


@app.task
def plugin_scan(task_id, target, script, scantype):
	script_path = 'gscan.tasks.plugins.' + script.split('.')[0]
	result = getattr(__import__(script_path, fromlist=["Plugin"]), "Plugin")(target).run()
	if len(result) > 0:
		if scantype == 'service':
			Service.objects.filter(taskid = task_id,ip = target,pluginpath = script).update(data=result)
		else:
			Weakfile.objects.filter(taskid = task_id,weakfile = target,pluginpath = script).update(data=result)



