Package ('webkit', '1.2.5',
	sources = [ 'http://webkitgtk.org/%{name}-%{version}.tar.gz' ],
	configure_flags = [
		'--disable-video',
		'--disable-xpath',
		'--disable-xslt',
		'--disable-wml',
		'--disable-ruby'
	]
)
