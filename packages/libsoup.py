class LibsoupPackage (GnomePackage):
	def __init__ (self):
		GnomePackage.__init__ (self, 'libsoup', '2.32', '0')
		self.configure_flags = [
			'--disable-gtk-doc',
			'--without-gnome'
		]

LibsoupPackage ()
