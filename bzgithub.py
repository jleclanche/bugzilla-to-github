#!/usr/bin/env python

import lxml
from github import Github
from pyquery import PyQuery as Q


__version__ = "0.1"
USER_AGENT = "Bugzilla/Migrate %s (PyGithub)" % (__version__)

TEMPLATE = """Reported by %(reporter)s on %(when)s:

%(description)s

Version: %(version)s
Platform: %(platform)s
System: %(system)s
Severity: %(severity)s
Bug ID: %(id)i
"""
COMMENT_TEMPLATE = """%(user)s wrote on %(when)s:

%(text)s
"""

# Optional: Add bugzilla-to-github mapping here. This is required to eg. preserve assignees
# WARNING: With lots of bugs, this may cause lots of unwanted spam
GITHUB_MAPPING = {
	# "bugzilla_username": "github_username"
}

LOGIN = "github_username"
OAUTH_TOKEN = "0123456789abcdef0123456789abcdef" # https://developer.github.com/v3/oauth/#create-a-new-authorization
REPOSITORY = "repository_org/repository_name"
BUGZILLA_XML = "bugzilla.xml"

try:
	from local_settings import *
except ImportError:
	pass


def get_bug_list():
	with open(BUGZILLA_XML, "rb") as f:
		xml = Q(f.read())
		return xml.find("bug")


def file_bugs(bugs):
	milestones = set(a["milestone"] for a in bugs.values() if a["milestone"])
	assignees = set(a["assignee"] for a in bugs.values())
	gh_assignees = set()
	for assignee in assignees:
		if assignee.github_username():
			gh_assignees.add(assignee)

	gh = Github(OAUTH_TOKEN, user_agent=USER_AGENT)
	repo = gh.get_repo(REPOSITORY)

	gh_milestones = {}
	for milestone in milestones:
		print("Creating milestone", milestone)
		gh_mstone = repo.create_milestone(milestone)
		gh_milestones[milestone] = gh_mstone

	for id in sorted(bugs.keys()):
		bug = bugs[id]
		body = TEMPLATE % bug
		assignee = None
		if bug["assignee"] in gh_assignees:
			assignee = bug["assignee"]
		milestone = None
		if bug["milestone"]:
			milestone = gh_milestones[bug["milestone"]]

		if id > 5: exit()

		print("Importing bugzilla #%i:" % (bug["id"]), bug["summary"])
		issue = repo.create_issue(bug["summary"], body)

		for comment in bug["comments"]:
			print("Comment by", comment["user"])
			issue.create_comment(COMMENT_TEMPLATE % comment)

		if bug["closed"]:
			print("Closing...")
			issue.edit(state="closed")


class User(object):
	def __init__(self, r):
		self.username = r.text
		self.name = r.attrib.get("name")

	def __repr__(self):
		return "<%s - %s>" % (self.username, self.name)

	def __str__(self):
		github = self.github_username()
		if github:
			return "@" + github
		return self.name or self.username

	def __hash__(self):
		return self.username.__hash__()

	def __eq__(self, other):
		if isinstance(other, self.__class__):
			return self.username == other.username
		return False

	def github_username(self):
		return GITHUB_MAPPING.get(self.username)


def get_comments(bug):
	comments = []
	for comment in bug.findall("long_desc"):
		comments.append({
			"text": comment.find("thetext").text,
			"user": User(comment.find("who")),
			"when": comment.find("bug_when").text,
		})
	return comments


def main():
	bugs = {}
	for bug in get_bug_list():
		id = int(bug.find("bug_id").text)
		bugs[id] = {
			"id": id,
			"product": bug.find("product").text,
			"status": bug.find("bug_status").text,
			"summary": bug.find("short_desc").text,
			"component": bug.find("component").text,
			"platform": bug.find("rep_platform").text,
			"system": bug.find("op_sys").text,
			"severity": bug.find("bug_severity").text,
			"version": bug.find("version").text,
			"when": bug.find("creation_ts").text,
			"milestone": bug.find("target_milestone").text,
			"assignee": User(bug.find("assigned_to")),
			"comments": get_comments(bug),
		}
		bugs[id]["closed"] = bugs[id]["status"] in ("RESOLVED", "VERIFIED", "CLOSED")
		bugs[id]["description"] = bugs[id]["comments"][0]["text"]
		bugs[id]["reporter"] = bugs[id]["comments"][0]["user"]
		del bugs[id]["comments"][0]
		if bugs[id]["milestone"] == "---":
			bugs[id]["milestone"] = None

	file_bugs(bugs)


if __name__ == "__main__":
	main()
