#!/usr/bin/env python
"""
 backports git tracker
=======================

The idea here is to put the backported drivers/etc. into a git tree
that follows the input git tree, for example wireless-testing or the
Linux upstream tree. This can then be used by end users who prefer
git over downloading tarballs, or developers who want to follow the
drivers from another tree, or maybe to bisect what change caused a
problem to occur (although this is less useful since lots of commits
need to be squashed in the output tree.)
"""

import sys, re, os, argparse, ConfigParser, shutil

# find self
source_dir = os.path.abspath(os.path.dirname(__file__))
source_dir = os.path.dirname(source_dir)
# add parent directory to path to get to lib/
sys.path.append(source_dir)
# import libraries we need
from lib import git, tempdir
import gentree

# you can increase this if you really want ...
# it will be very slow then
MAX_COMMITS = 100

PREFIX = 'x-git-tracker-'
FAIL = 'failed'


def update_cache_objects(gittree, objdir):
    if not os.path.isdir(objdir):
        git.clone(gittree, objdir, options=['--bare'])
    else:
        git.set_origin(gittree, objdir)
        git.remote_update(objdir)

def handle_commit(args, msg, branch, treename, kernelobjdir, tmpdir, wgitdir, backport_rev, kernel_rev,
                  prev_kernel_rev=None, defconfig=None):
    log = []
    def logwrite(l):
        log.append(l)
    wdir = os.path.join(tmpdir, kernel_rev)
    os.makedirs(wdir)
    try:
        failure = gentree.process(kernelobjdir, wdir, open(args.copy_list, 'r'),
                                  git_revision=kernel_rev,
                                  base_name=tree, logwrite=logwrite,
                                  kernel_version_name="(see git)",
                                  backport_version_name="(see git)")

        newline = '\n'
        if failure:
            msg = 'Failed to create backport\n\n%s%s: %s' % (PREFIX, FAIL, failure)
            for l in log:
                print l
            newline=''
            if prev_kernel_rev:
                msg += '\n%sprefail-%s: %s' % (PREFIX, tree, prev_kernel_rev)

        os.rename(wgitdir, os.path.join(wdir, '.git'))

        if not failure:
            git.rm(opts=['--ignore-unmatch', '-q', '--cached', '-r', '.'], tree=wdir)
            if defconfig:
                os.symlink('defconfigs/%s' % defconfig, os.path.join(wdir, 'defconfig'))
            git.add('.', tree=wdir)
        else:
            git.reset(opts=['-q'], tree=wdir)

        msg += '''%(newline)s
%(PREFIX)sbackport: %(bprev)s
%(PREFIX)s%(tree)s: %(krev)s
''' % {
        'newline': newline,
        'PREFIX': PREFIX,
        'bprev': backport_rev,
        'tree': treename,
        'krev': kernel_rev,
      }

        env = git.commit_env_vars(kernel_rev, tree=kernelobjdir)
        git.commit(msg, tree=wdir, env=env, opts=['-q', '--allow-empty'])
        git.push(opts=['-f', '-q', 'origin', branch], tree=wdir)
        os.rename(os.path.join(wdir, '.git'), wgitdir)
    finally:
        if os.path.isdir(wdir):
            shutil.rmtree(wdir)

    return failure

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='backport git tracker')
    parser.add_argument('--config', metavar='<config-file>', type=str,
                        default=os.path.join(source_dir, 'devel', 'git-tracker.ini'),
                        help='Configuration file for the tracker')
    parser.add_argument('--copy-list', metavar='<listfile>', type=str,
                        default=os.path.join(source_dir, 'copy-list'),
                        help='File containing list of files/directories to copy')
    args = parser.parse_args()

    # Load configuration
    config = ConfigParser.SafeConfigParser({'branches': 'master'})
    config.read(args.config)

    # check required parameters
    trees = config.sections()
    if not trees:
        print "No trees are defined, see git-tracker.ini.example!"
        sys.exit(3)
    for tree in trees:
        if not config.has_option(tree, 'input'):
            print "No input defined in section %s" % tree
            sys.exit(3)
        if not config.has_option(tree, 'output'):
            print "No output defined in section %s" % tree
            sys.exit(3)

    with tempdir.tempdir() as kernel_tmpdir:
        # get cachedir, or use temporary directory
        if not config.has_option('DEFAULT', 'cachedir'):
            cachedir = os.path.join(kernel_tmpdir, 'cachedir')
        else:
            cachedir = config.get('DEFAULT', 'cachedir')

        if not os.path.isdir(cachedir):
            os.makedirs(cachedir)
        kernelobjdir = os.path.join(cachedir, 'kernel')

        backport_rev = git.rev_parse(tree=source_dir)

        for tree in trees:
            input = config.get(tree, 'input')
            output = config.get(tree, 'output')
            defconfig = None
            if config.has_option(tree, 'defconfig'):
                defconfig = config.get(tree, 'defconfig')
            branches = [r.strip() for r in config.get(tree, 'branches').split(',')]

            update_cache_objects(input, kernelobjdir)

            wgitref = os.path.join(cachedir, 'backport-' + tree)

            update_cache_objects(output, wgitref)

            for branch in branches:
                with tempdir.tempdir() as branch_tmpdir:
                    wgitdir = os.path.join(branch_tmpdir, 'work.git')

                    git.clone(output, wgitdir, ['--reference', wgitref, '--bare', '--single-branch', '--branch', branch])
                    git.remove_config('core.bare', tree=wgitdir)
                    git.set_origin(output, wgitdir)

                    kernel_head = git.ls_remote(branch, tree=kernelobjdir)

                    old_data = {}
                    try:
                        msg = git.commit_message('HEAD', wgitdir)
                        for line in msg.split('\n'):
                            line = line.strip()
                            if line.startswith(PREFIX):
                                k, v = line[len(PREFIX):].split(':')
                                k = k.strip()
                                v = v.strip()
                                old_data[k] = v
                    except git.ExecutionError:
                        # the repository is probably still empty ...
                        pass
                    if not 'backport' in old_data or not tree in old_data:
                        # assume it's all new, don't log anything ...
                        handle_commit(args, "Initialize backport branch\n\nCreate the new git tracker backport branch.",
                                      branch, tree, kernelobjdir,
                                      branch_tmpdir, wgitdir, backport_rev,
                                      kernel_head, defconfig=defconfig)
                        continue
                    if old_data['backport'] == backport_rev and old_data[tree] == kernel_head:
                        continue
                    prefail = 'prefail-%s' % tree
                    if old_data[tree] == kernel_head and not prefail in old_data:
                        handle_commit(args, "Update backport tree\n\n",
                                      branch, tree, kernelobjdir,
                                      branch_tmpdir, wgitdir, backport_rev,
                                      kernel_head, defconfig=defconfig)
                        continue
                    # update from old to new
                    if prefail in old_data:
                        prev = old_data[prefail]
                    else:
                        prev = old_data[tree]
                    commits = git.log_commits(prev, kernel_head, tree=kernelobjdir)
                    if len(commits) > MAX_COMMITS:
                        print "too many commits (%d)!" % len(commits)
                        sys.exit(10)
                    for commit in commits:
                        print 'updating to commit', commit
                        msg = git.commit_message(commit, kernelobjdir)
                        try:
                            # add information about commits that went into this
                            shortlog = git.shortlog(prev, '%s^2' % commit,
                                                    tree=kernelobjdir)
                            msg += "\nCommits in this merge:\n\n" + shortlog
                        except git.ExecutionError, e:
                            # will fail if it wasn't a merge commit
                            pass
                        failure = handle_commit(args, msg, branch, tree, kernelobjdir, branch_tmpdir,
                                                wgitdir, backport_rev, commit,
                                                prev_kernel_rev=prev, defconfig=defconfig)
                        if not failure:
                            prev = commit