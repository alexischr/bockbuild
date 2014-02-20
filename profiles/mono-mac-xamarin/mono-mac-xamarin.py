#!/usr/bin/python -B -u

import itertools
import os
import re
import shutil
import string
import sys
import tempfile

sys.path.append('../..')

from bockbuild.darwinprofile import DarwinProfile
from bockbuild.util.util import *
from packages import MonoReleasePackages
from glob import glob


class MonoReleaseProfile(DarwinProfile, MonoReleasePackages):
    def __init__(self):
        self.MONO_ROOT = "/Library/Frameworks/Mono.framework"
        self.RELEASE_VERSION = os.getenv('MONO_VERSION')
        self.BUILD_NUMBER = "0"
        self.MRE_GUID = "432959f9-ce1b-47a7-94d3-eb99cb2e1aa8"
        self.MDK_GUID = "964ebddd-1ffe-47e7-8128-5ce17ffffb05"

        if self.RELEASE_VERSION is None:
            raise Exception("Please define the environment variable: MONO_VERSION")

        versions_root = os.path.join(self.MONO_ROOT, "Versions")
        self.release_root = os.path.join(versions_root, self.RELEASE_VERSION)

        DarwinProfile.__init__(self, self.release_root)
        MonoReleasePackages.__init__(self)

        self.self_dir = os.path.realpath(os.path.dirname(sys.argv[0]))
        self.packaging_dir = os.path.join(self.self_dir, "packaging")

        aclocal_dir = os.path.join(self.prefix, "share", "aclocal")
        if not os.path.exists(aclocal_dir):
            os.makedirs(aclocal_dir)

    def build(self):
        if not os.path.exists(os.path.join(self.release_root, "bin")):
            log(0, "Rebuilding world - new prefix: " + self.release_root)
            shutil.rmtree(self.build_root, ignore_errors=True)
        DarwinProfile.build(self)

    def make_package_symlinks(self, root):
        os.symlink(self.prefix, os.path.join(root, "Versions", "Current"))
        currentlink = os.path.join(self.MONO_ROOT, "Versions", "Current")
        links = [
            ("bin", "Commands"),
            ("include", "Headers"),
            ("lib", "Libraries"),
            ("", "Home"),
            (os.path.join("lib", "libmono-2.0.dylib"), "Mono")
        ]
        for srcname, destname in links:
            src = os.path.join(currentlink, srcname)
            dest = os.path.join(root, destname)
            #If the symlink exists, we remove it so we can create a fresh one
            if os.path.exists(dest):
                os.unlink(dest)
            os.symlink(src, dest)

    def find_git(self):
        self.git = 'git'
        for git in ['/usr/local/bin/git', '/usr/local/git/bin/git', '/usr/bin/git']:
			if os.path.isfile (git):
				self.git = git
				break

    def calculate_updateid(self):
        # Create the updateid
        if os.getenv('BOCKBUILD_ADD_BUILD_NUMBER'):
            self.find_git()
            version_number_str = 'cd build-root/mono; %s log `%s blame configure.in HEAD | grep AC_INIT | sed \'s/ .*//\' `..HEAD --oneline | wc -l | sed \'s/ //g\'' % (self.git, self.git)
            build_number = backtick(version_number_str)
            print "Calculating commit distance, %s" % (build_number)
            self.BUILD_NUMBER = " ".join(build_number)
            self.FULL_VERSION = self.RELEASE_VERSION + "." + self.BUILD_NUMBER
        else:
            self.BUILD_NUMBER="0"
            self.FULL_VERSION = self.RELEASE_VERSION

        parts = self.RELEASE_VERSION.split(".")
        version_list = (parts + ["0"] * (3 - len(parts)))[:4]
        for i in range(1, 3):
            version_list[i] = version_list[i].zfill(2)
            self.updateid = "".join(version_list)
            self.updateid += self.BUILD_NUMBER.replace(".", "").zfill(9 - len(self.updateid))

    # creates and returns the path to a working directory containing:
    #   PKGROOT/ - this root will be bundled into the .pkg and extracted at /
    #   uninstallMono.sh - copied onto the DMG
    #   Info{_sdk}.plist - used by packagemaker to make the installer
    #   resources/ - other resources used by packagemaker for the installer
    def setup_working_dir(self):
        tmpdir = tempfile.mkdtemp()
        monoroot = os.path.join(tmpdir, "PKGROOT", self.MONO_ROOT[1:])
        versions = os.path.join(monoroot, "Versions")
        os.makedirs(versions)

        self.calculate_updateid();

        print "setup_working_dir " + tmpdir
        # setup metadata
        backtick('rsync -aP %s/* %s' % (self.packaging_dir, tmpdir))
        parameter_map = {
            '@@MONO_VERSION@@': self.RELEASE_VERSION,
            '@@MONO_RELEASE@@': self.BUILD_NUMBER,
            '@@MONO_VERSION_RELEASE@@': self.RELEASE_VERSION + '_' + self.BUILD_NUMBER,
            '@@MONO_PACKAGE_GUID@@': self.MRE_GUID,
            '@@MONO_CSDK_GUID@@': self.MDK_GUID,
            '@@MONO_VERSION_RELEASE_INT@@': self.updateid,
            '@@PACKAGES@@': string.join(set([root for root, ext in map(os.path.splitext, os.listdir(self.build_root))]), "\\\n"),
            '@@DEP_PACKAGES@@': ""
        }
        for dirpath, d, files in os.walk(tmpdir):
            for name in files:
                if not name.startswith('.'):
                    replace_in_file(os.path.join(dirpath, name), parameter_map)

        self.make_package_symlinks(monoroot)

        # copy to package root
        backtick('rsync -aP "%s" "%s"' % (self.release_root, versions))

        return tmpdir

    def apply_blacklist(self, working_dir, blacklist_name):
        blacklist = os.path.join(working_dir, blacklist_name)
        root = os.path.join(working_dir, "PKGROOT", self.release_root[1:])
        backtick(blacklist + ' "%s"' % root)

    def run_pkgbuild(self, working_dir, package_type, codesign_key):
        info = self.package_info(package_type)
        output = os.path.join(self.self_dir, info["filename"])
        temp = os.path.join(self.self_dir, "mono-%s.pkg" % package_type)
        identifier = "com.xamarin.mono-" + info["type"] + ".pkg"
        resources_dir = os.path.join(working_dir, "resources")
        distribution_xml = os.path.join(resources_dir, "distribution.xml")

        old_cwd = os.getcwd()
        os.chdir(working_dir)
        pkgbuild = "/usr/bin/pkgbuild"
        identity = "Developer ID Installer: Xamarin Inc"
        pkgbuild_cmd = ' '.join([pkgbuild,
                                 "--identifier " + identifier,
                                 "--root '%s/PKGROOT'" % working_dir,
                                 "--version '%s'" % self.RELEASE_VERSION,
                                 "--install-location '/'",
                                 # "--sign '%s'" % identity,
                                 "--scripts '%s'" % resources_dir,
                                 os.path.join(working_dir, "mono.pkg")])
        print pkgbuild_cmd
        backtick(pkgbuild_cmd)

        productbuild = "/usr/bin/productbuild"
        productbuild_cmd = ' '.join([productbuild,
                                     "--resources %s" % resources_dir,
                                     "--distribution %s" % distribution_xml,
                                     # "--sign '%s'" % identity,
                                     "--package-path %s" % working_dir,
                                     temp])
        print productbuild_cmd
        backtick(productbuild_cmd)

        productsign = "/usr/bin/productsign"
        productsign_cmd = ' '.join([productsign,
                                    "-s '%s'" % codesign_key,
                                    "'%s'" % temp,
                                    "'%s'" % output])
        print productsign_cmd
        backtick(productsign_cmd)
        os.remove(temp)

        os.chdir(old_cwd)
        return output

    def make_updateinfo(self, working_dir, guid):
        updateinfo = os.path.join(
            working_dir, "PKGROOT", self.release_root[1:], "updateinfo")
        with open(updateinfo, "w") as updateinfo:
            updateinfo.write(guid + ' ' + self.updateid + "\n")

    def package_info(self, pkg_type):
        version = self.FULL_VERSION
        info = (pkg_type, version)
        filename = "MonoFramework-%s-%s.macos10.xamarin.x86.pkg" % info
        return {
            "type": pkg_type,
            "filename": filename,
            "title": "Mono Framework %s %s " % info
        }

    def build_package(self):
        working = self.setup_working_dir()
        # uninstall_script = os.path.join(working, "uninstallMono.sh")

        # Unlock the keychain
        key = os.getenv("CODESIGN_KEY")
        password = os.getenv("CODESIGN_KEYCHAIN_PASSWORD")
        output = backtick("security -v find-identity")
        if key not in " ".join(output):
            raise Exception("%s is not a valid codesign key" % key)

        if password:
            print "Unlocking the keychain"
            backtick("security unlock-keychain -p %s" % password)
        else:
            raise Exception("CODESIGN_KEYCHAIN_PASSWORD needs to be defined")

        # make the MDK
        self.apply_blacklist(working, 'mdk_blacklist.sh')
        self.make_updateinfo(working, self.MDK_GUID)
        mdk_pkg = self.run_pkgbuild(working, "MDK", key)
        print "Saving: " + mdk_pkg
        self.verify_codesign(mdk_pkg)
        # self.make_dmg(mdk_dmg, title, mdk_pkg, uninstall_script)

        # make the MRE
        self.apply_blacklist(working, 'mre_blacklist.sh')
        self.make_updateinfo(working, self.MRE_GUID)
        mre_pkg = self.run_pkgbuild(working, "MRE", key)
        print "Saving: " + mre_pkg
        self.verify_codesign(mre_pkg)
        # self.make_dmg(mre_dmg, title, mre_pkg, uninstall_script)

        shutil.rmtree(working)

    def verify_codesign(self, pkg):
        oldcwd = os.getcwd()
        try:
            name = os.path.basename(pkg)
            pkgdir = os.path.dirname(pkg)
            os.chdir(pkgdir)
            spctl = "/usr/sbin/spctl"
            spctl_cmd = ' '.join(
                [spctl, "-vvv", "--assess", "--type install", name, "2>&1"])
            output = backtick(spctl_cmd)

            if "accepted" in " ".join(output):
                log(0, "%s IS SIGNED" % pkg)
            else:
                log(0, "%s IS NOT SIGNED" % pkg)
        finally:
            os.chdir(oldcwd)

    def generate_dsym(self):
        for path, dirs, files in os.walk(self.prefix):
            for name in files:
                f = os.path.join(path, name)
                file_type = backtick('file "%s"' % f)
                if "dSYM" in f:
                    continue
                if "Mach-O" in "".join(file_type):
                    print "Generating dsyms for %s" % f
                    backtick('dsymutil "%s"' % f)

    def verify(self, f):
        result = " ".join(backtick("otool -L " + f))
        regex = os.path.join(self.MONO_ROOT, "Versions", r"(\d+\.\d+\.\d+)")
        match = re.search(regex, result).group(1)
        if self.RELEASE_VERSION not in match:
            raise Exception("%s references Mono %s\n%s" % (f, match, result))

    def verify_binaries(self, binaries):
        for path, dirs, files in os.walk(binaries):
            for name in files:
                f = os.path.join(path, name)
                file_type = backtick('file "%s"' % f)
                if "Mach-O executable" in "".join(file_type):
                    self.verify(f)

    def install_root(self):
        return os.path.join(self.MONO_ROOT, "Versions", self.RELEASE_VERSION)

    def fix_line(self, line, matcher):
        def insert_install_root(matches):
            root = self.install_root()
            captures = matches.groupdict()
            return 'target="%s"' % os.path.join(root, "lib", captures["lib"])

        if matcher(line):
            pattern = r'target="(?P<lib>.+\.dylib)"'
            result = re.sub(pattern, insert_install_root, line)
            return result
        else:
            return line

    def fix_dllmap(self, config, matcher):
        handle, temp = tempfile.mkstemp()
        with open(config) as c:
            with open(temp, "w") as output:
                for line in c:
                    output.write(self.fix_line(line, matcher))
        os.rename(temp, config)
        os.system('chmod a+r %s' % config)

    def fix_libMonoPosixHelper(self):
        config = os.path.join(self.prefix, "etc", "mono", "config")
        self.fix_dllmap(
            config, lambda line: "libMonoPosixHelper.dylib" in line)

    def fix_gtksharp_configs(self):
        libs = [
            'atk-sharp',
            'gdk-sharp',
            'glade-sharp',
            'glib-sharp',
            'gtk-dotnet',
            'gtk-sharp',
            'pango-sharp'
        ]
        gac = os.path.join(self.install_root(), "lib", "mono", "gac")
        confs = [glob(os.path.join(gac, x, "*", "*.dll.config")) for x in libs]
        for c in itertools.chain(*confs):
            print "Fixing up " + c
            self.fix_dllmap(c, lambda line: "dllmap" in line)

    # THIS IS THE MAIN METHOD FOR MAKING A PACKAGE
    def package(self):
        self.fix_libMonoPosixHelper()
        self.fix_gtksharp_configs()
        self.generate_dsym()
        self.verify_binaries(os.path.join(self.release_root, "bin"))
        blacklist = os.path.join(self.packaging_dir, 'mdk_blacklist.sh')
        backtick(blacklist + ' ' + self.release_root)
        self.build_package()

MonoReleaseProfile().build()

