var _____WB$wombat$assign$function_____ = function(name) {return (self._wb_wombat && self._wb_wombat.local_init && self._wb_wombat.local_init(name)) || self[name]; };
if (!self.__WB_pmw) { self.__WB_pmw = function(obj) { this.__WB_source = obj; return this; } }
{
  let window = _____WB$wombat$assign$function_____("window");
  let self = _____WB$wombat$assign$function_____("self");
  let document = _____WB$wombat$assign$function_____("document");
  let location = _____WB$wombat$assign$function_____("location");
  let top = _____WB$wombat$assign$function_____("top");
  let parent = _____WB$wombat$assign$function_____("parent");
  let frames = _____WB$wombat$assign$function_____("frames");
  let opener = _____WB$wombat$assign$function_____("opener");


/******************************************************************************
*     GAME SETTINGS
*******************************************************************************/

// Ad Settings
var Ad_Duration = 5;						// Seconds
var Ad_Width = null;						// If set to 'null', the width of the game screen is used
var Ad_Height = null;						// If set to 'null', the height of the game screen is used
var Game_BgColor = 'lightsteelblue';
var Run_Preroll = true;
var Run_Midroll = true;
var Run_Postroll = true;

// Ad Page(s)
var Preroll_Src_Path = 'preroll.html';
var Midroll_Src_Path = 'midroll.html';
var Postroll_Src_Path = 'postroll.html';
var Min_Time_Between_Ads = 60;				// Seconds

// Upsell Settings
var Enable_Upsell = true;
var Upsell_Url = 'http://www.warrobotdoge.com/bookworm.com'; // This doesn't get used if Enable_Upsell = false

// Absolute Path to Game Files
// (If left blank, it will be assumed that the game files are in the same folder as this include file.)
var Base_Path = '';

// Paths to ActiveX Loader Files
var Logo_Cab_Path = 'logo.cab';
var IE_Plugin_Path = 'popcaploader_v10.cab#version=1,0,0,10';
var FireFox_Plugin_Path = 'PopCapPluginInstaller_v2.exe';

var Upsell_Ad_Frequency = 4;
  
/******************************************************************************
*     POPCAPGAME BASE
*******************************************************************************/

var thePopCapGame = null;

function popCapGame(gameName, id, gameWidth, gameHeight)
{
    popCapGame.prototype.displayName = gameName;
    popCapGame.prototype.id = id;
    popCapGame.prototype.width = gameWidth;
    popCapGame.prototype.height = gameHeight;
    
    popCapGame.prototype.paramNames = new Array();
    popCapGame.prototype.params = new Array();	
    popCapGame.prototype.hosts = new Array();
    popCapGame.prototype.signatures = new Array();
	
    popCapGame.prototype.partnerName = '';
	popCapGame.prototype.basePath = '';
    popCapGame.prototype.upsellUrl = '';
	popCapGame.prototype.objectSetup = '';
	popCapGame.prototype.containerId = 'gamediv';
	
	popCapGame.prototype.LoadBroadcast = 'LoadBroadcast';
	popCapGame.prototype.SessionReady = 'SessionReady';
	popCapGame.prototype.GameReady = 'GameReady';
	popCapGame.prototype.ScoreBroadcast = 'ScoreBroadcast';
	popCapGame.prototype.GameBreak = 'GameBreak';
	popCapGame.prototype.ScoreSubmit = 'ScoreSubmit';
	popCapGame.prototype.GameEnd = 'GameEnd';
	popCapGame.prototype.CustomEvent = 'CustomEvent';
	
    popCapGame.prototype.levelCount = 0;
	popCapGame.prototype.gameObject = null;
    popCapGame.prototype.hide = false;
}

popCapGame.prototype.pathConcat = function(first,last)
{
	if (first == '') return last;
	if (first.search(/\/$/) == -1) return first + '/' + last;
	return first + last;
}

popCapGame.prototype.applyBasePath = function()
{
}

popCapGame.prototype.write = function()
{
}

popCapGame.prototype.getParams = function()
{
}

popCapGame.prototype.sendNotification = function(method,params)
{
}

popCapGame.prototype.receiveNotification = function(method,params)
{
	if (method == this.LoadBroadcast) { LoadBroadcast(params); }
	else if (method == this.SessionReady) { SessionReady(params); }
	else if (method == this.GameReady) { GameReady(params); }
	else if (method == this.ScoreBroadcast) { ScoreBroadcast(params); }
	else if (method == this.GameBreak) { GameBreak(params); }
	else if (method == this.ScoreSubmit) { ScoreSubmit(params); }
	else if (method == this.GameEnd) { GameEnd(params); }
	else if (method == this.CustomEvent) { CustomEvent(params); }
	else {}	
}

/*---- CALLS TO GAME ----*/

popCapGame.prototype.SessionStart = function()
{
	this.sendNotification('SessionStart','');
}

popCapGame.prototype.GameStart = function()
{
	this.sendNotification('GameStart','');
}

popCapGame.prototype.GameMenu = function()
{
	this.sendNotification('GameMenu','');
}

popCapGame.prototype.GameContinue = function()
{
	this.sendNotification('GameContinue','');
}

popCapGame.prototype.CustomReturn = function(params)
{
	this.sendNotification('CustomReturn',params);
}

popCapGame.prototype.Mute = function(isMute)
{
	this.sendNotification(isMute ? 'MuteOn' : 'MuteOff','');
}

popCapGame.prototype.Pause = function(isPause)
{
	this.sendNotification(isPause ? 'PauseOn' : 'PauseOff','');
}

/*---- EVENT HANDLING ----*/

popCapGame.prototype.OnLoadBroadcast = function(params)
{
}

popCapGame.prototype.OnSessionReady = function(params)
{

	theAdSpot.isOwnerLoaded = true;	
	if (!this.hide) this.SessionStart();

}

popCapGame.prototype.OnGameReady = function(params)
{
	this.GameStart();
}

popCapGame.prototype.OnScoreBroadcast = function(params)
{    
}

popCapGame.prototype.OnGameBreak = function(params)
{

	if (params == 'adCompleted')
		this.GameContinue();
	else
		theAdSpot.display('GameBreak');

}

popCapGame.prototype.OnScoreSubmit = function(params)
{
}

popCapGame.prototype.OnGameEnd = function(params)
{

	if (params == 'adCompleted')
		this.GameMenu();
	else
		theAdSpot.display('GameEnd');

}

popCapGame.prototype.OnCustomEvent = function(params)
{
    if (Enable_Upsell) window.open(this.upsellUrl);
    this.CustomReturn(params);
}

/******************************************************************************
*     ACTIVEX : POPCAPGAME
*******************************************************************************/

popCapAXGame.prototype = popCapGame.prototype;
popCapAXGame.prototype.constructor = popCapAXGame;
popCapAXGame.prototype.baseClass = popCapGame.prototype.constructor;

function popCapAXGame(gameName, id, gameWidth, gameHeight, gameDll, gameCab)
{	
    popCapGame(gameName, id, gameWidth, gameHeight);

    popCapAXGame.prototype.gameDll = gameDll;
    popCapAXGame.prototype.gameCab = gameCab;
	
    popCapAXGame.prototype.logoCab = 'logo.cab';
    popCapAXGame.prototype.loaderCab = 'popcaploader_v10.cab#version=1,0,0,10';
    popCapAXGame.prototype.plugin = 'PopCapPluginInstaller_v2.exe';
	popCapAXGame.prototype.isInIE = (document.all != null);
}

popCapAXGame.prototype.applyBasePath = function()
{

	this.gameCab = this.pathConcat(this.basePath, this.gameCab);
}

popCapAXGame.prototype.write = function()
{
	if (this.isInIE || this.checkForPlugin())
	{

		this.applyBasePath();

		this.objectSetup = '<!--[if !IE]><!-->\r\n';
	    this.objectSetup += '<div id="' + this.containerId + '"';
	    if (this.hide) this.objectSetup += ' style="visibility: hidden;"';
		this.objectSetup += '>\r\n';
		this.objectSetup += '<embed type="application/x-popcaploader;version=1.0.0.1" ';
		this.objectSetup += 'id="'+this.id+'" ';
		this.objectSetup += 'numhosts="'+this.hosts.length+'" ';
		for(var i = 0; i < this.hosts.length; i++)
		{
			this.objectSetup += 'host'+(i+1)+'="' + this.hosts[i] + '" ';
			this.objectSetup += 'hostsig' + (i+1) + '="' + this.signatures[i] + '" ';
		}
		this.objectSetup += 'gamename="'+this.gameDll+'" ';
		this.objectSetup += 'partnername="'+this.partnerName+'" ';
		this.objectSetup += 'displayname="'+this.displayName+'" ';
		this.objectSetup += 'gamecab="'+this.gameCab+'" ';
		this.objectSetup += 'logocab="'+this.logoCab+'" ';
		this.objectSetup += this.getParams();
		this.objectSetup += 'height="'+this.height+'" ';
		this.objectSetup += 'width="'+this.width+'"></embed>\r\n';
		this.objectSetup += '</div>\r\n';
		this.objectSetup += '<script language="JavaScript" type="text/javascript">\r\n';
		this.objectSetup += 'function PopcapNotification_'+this.id+'(method,param)\r\n';
		this.objectSetup += '{\r\n';
		this.objectSetup += '  thePopCapGame.receiveNotification(method,param);\r\n';
		this.objectSetup += '}\r\n';
		this.objectSetup += '</script>\r\n';
		this.objectSetup += '<!--<![endif]-->\r\n';
		this.objectSetup += '<!--[if IE]>\r\n';
	    this.objectSetup += '<div id="' + this.containerId + '"';
	    if (this.hide) this.objectSetup += ' style="visibility: hidden;"';
		this.objectSetup += '>\r\n';
		this.objectSetup += '<object ';
		this.objectSetup += 'id="'+this.id+'" ';
		this.objectSetup += 'classid="clsid:DF780F87-FF2B-4DF8-92D0-73DB16A1543A" ';
		this.objectSetup += 'codebase="'+this.loaderCab+'" ';
		this.objectSetup += 'width='+this.width+' ';
		this.objectSetup += 'height='+this.height+'>\r\n';
		for(i = 0; i < this.hosts.length; i++)
		{
			this.objectSetup += '<param name="host' + (i+1) + '" value="' + this.hosts[i] + '"/>\r\n';
			this.objectSetup += '<param name="hostsig' + (i+1) + '" value="' + this.signatures[i] + '"/>\r\n';
		}
		this.objectSetup += '<param name="hosts" value="' + this.hosts.length + '">\r\n';
		this.objectSetup += '<param name="gamename" value="'+this.gameDll+'">\r\n';
		this.objectSetup += '<param name="partnername" value="'+this.partnerName+'">\r\n';
		this.objectSetup += '<param name="displayname" value="'+this.displayName+'">\r\n';
		this.objectSetup += '<param name="gamecab" value="'+this.gameCab+'">\r\n';
		this.objectSetup += '<param name="logocab" value="'+this.logoCab+'">\r\n';
		this.objectSetup += this.getParams();
		this.objectSetup += '</object>\r\n';
		this.objectSetup += '</div>\r\n';
		this.objectSetup += '<script for="'+this.id+'" event="PopcapNotification(method,params)" language="JavaScript">\r\n';
		this.objectSetup += 'thePopCapGame.receiveNotification(method,params);\r\n';
		this.objectSetup += '</script>\r\n';
		this.objectSetup += '<![endif]-->\r\n';
		
		document.write(this.objectSetup);
		this.gameObject = document.getElementById(this.id);
	}
}

popCapAXGame.prototype.getParams = function()
{
    var tags = '';

	if (this.isInIE)
	{
		for(var i = 0; i < this.paramNames.length; i++)
		{
			if (this.params[i].toString().search(/\.cab/) == -1)
				tags += '<param name="'+this.paramNames[i]+'" value="'+this.params[i]+'">\r\n';
			else
				tags += '<param name="'+this.paramNames[i]+'" value="'+this.pathConcat(this.basePath, this.params[i])+'">\r\n';
		}
	}
	else
	{
		for(var i = 0; i < this.paramNames.length; i++)
		{
			if (this.params[i].toString().search(/\.cab/) == -1)
				tags += this.paramNames[i]+'="'+this.params[i]+'"\r\n';
			else
				tags += this.paramNames[i]+'="'+this.pathConcat(this.basePath, this.params[i])+'"\r\n';
		}
	}

    return tags;
}

popCapAXGame.prototype.reloadPlugin = function()
{
    navigator.plugins.refresh(true);
    window.location.href = window.location.href;
}

popCapAXGame.prototype.checkForPlugin  = function()
{
	try
	{
		var pluginType = 'application/x-popcaploader;version=1.0.0.1';
		mimetype = navigator.mimeTypes[pluginType];

		if (!(mimetype && mimetype.enabledPlugin && mimetype.type==pluginType))
		{
			document.write('<br>You need to get the PopCap Plugin to run this game.<br>');
			document.write('Get the PopCap Plugin <a href="'+this.plugin+'">here</a>!<br>');
			document.write('After installing the plugin, launch the game <a href="javascript:;" onclick="thePopCapGame.reloadPlugin()">here</a>!<br>');
			
			return false;
		}
		else return true;
	}
	catch (e) { }
}

popCapAXGame.prototype.sendNotification = function(method,params)
{
    this.gameObject.PopcapNotify(method,params);
}

popCapAXGame.prototype.OnGameBreak = function(params)
{

	if (params == 'adCompleted')
	{
		this.GameContinue();
	}
	else
	{
	this.levelCount++;
	if (Enable_Upsell && this.levelCount % Upsell_Ad_Frequency == 0)
		this.sendNotification('GameUpsell');
	else if (typeof(theAdSpot) == 'undefined')
		theAdSpot.display('GameBreak');
	else
		this.GameContinue();
	}

}

/******************************************************************************
*     MSN API FUNCTIONS (Registered in ActionScript 3 Games)
*******************************************************************************/

LoadBroadcast = function(params)
{
	thePopCapGame.OnLoadBroadcast(params);
}

SessionReady = function(params)
{
	thePopCapGame.OnSessionReady(params);
}

GameReady = function(params)
{
	thePopCapGame.OnGameReady(params);
}

ScoreBroadcast = function(params)
{
	thePopCapGame.OnScoreBroadcast(params);
}

GameBreak = function(params)
{
	thePopCapGame.OnGameBreak(params);
}

ScoreSubmit = function(params)
{
	thePopCapGame.OnScoreSubmit(params);
}

GameEnd = function(params)
{
	thePopCapGame.OnGameEnd(params);
}

CustomEvent = function(params)
{
	thePopCapGame.OnCustomEvent(params);
}

/******************************************************************************
*     AD SUPPORT
*******************************************************************************/

var theAdSpot = null;

function adSpot(id, theGame)
{
    adSpot.prototype.id = id;
    adSpot.prototype.owner = theGame;
	
    adSpot.prototype.width = 0;
    adSpot.prototype.height = 0;	
    adSpot.prototype.countdown = 0;
    adSpot.prototype.lastShown = 0;
    adSpot.prototype.duration = 5;
	adSpot.prototype.adObject = null;
	adSpot.prototype.ownerContainer = null;
    adSpot.prototype.globalTimer = null;
	adSpot.prototype.prerollSrc = 'preroll.html';	
	adSpot.prototype.ownerBgcolor = 'white';
    adSpot.prototype.showPreroll = false;
	adSpot.prototype.showMidroll = false;
	adSpot.prototype.showPostroll = false;

	adSpot.prototype.breakEvent = '';
	adSpot.prototype.isOwnerLoaded = false;
    adSpot.prototype.wait = 60;
	adSpot.prototype.midrollSrc = 'midroll.html';
	adSpot.prototype.postrollSrc = 'postroll.html';

    adSpot.prototype.isInIE = (document.all != null);
}

adSpot.prototype.write = function()
{
	this.setDimensions();

	document.write('<style type="text/css">');
	document.write('#'+this.id+' { ');
	document.write('position: absolute; ');
	document.write('top: 15px; ');
	document.write('left: 10px; ');
	document.write('z-index: 1; ');
	document.write('visibility: hidden; ');
	document.write('display: none; ');
	document.write('width: '+this.width+'; ');
	document.write('height: '+this.height+'; ');
	document.write('}</style>\r\n');
	document.write('<div id='+this.id+'>\r\n');
	
	document.write('<iframe id="spot" name="spot" ');
	document.write('width="'+this.width+'" ');
	document.write('height="'+this.height+'" ');
	document.write('src="'+this.prerollSrc+'" ');
	document.write('scrolling="no" ');
	document.write('frameborder="0" border="0" ');
	document.write('marginheight="0" marginwidth="0" ');
	document.write('oncontextmenu="return false"></iframe>\r\n');
	
	document.write('</div>\r\n');
	this.adObject = document.getElementById(this.id);

}

adSpot.prototype.setDimensions = function()
{	
	var isTaller = (this.height != null && this.height > this.owner.height);
	var isWider = (this.width != null && this.width > this.owner.width);
	
	this.ownerContainer = document.getElementById(this.owner.containerId);
	
	if (!isTaller) this.height = this.owner.height;
	if (!isWider) this.width = this.owner.width;
	
	if (!isTaller && !isWider) return;
	
	if (this.ownerContainer)
	{
		var padWidth = this.width/2 - this.owner.width/2;
		var padHeight = this.height/2 - this.owner.height/2;		
		if (this.isInIE)
		{
			this.ownerContainer.style.width = this.width;
			this.ownerContainer.style.height = this.height;
		}
		else
		{
			this.ownerContainer.style.width = this.width - padWidth;
			this.ownerContainer.style.height = this.height - padHeight;
		}
		this.ownerContainer.style.backgroundColor = this.ownerBgcolor;
		this.ownerContainer.style.paddingLeft = padWidth;
		this.ownerContainer.style.paddingTop = padHeight;
	}
}

adSpot.prototype.timer = function()
{
    if (this.countdown > 0) this.countdown--;

    if (this.countdown == 0) this.endDisplay();
    else this.globalTimer = setTimeout('theAdSpot.timer()',1000);
}

adSpot.prototype.resumeGame = function()
{
	if (this.breakEvent == 'GameBreak')
		this.owner.OnGameBreak('adCompleted');
	else
		this.owner.OnGameEnd('adCompleted');
}

adSpot.prototype.display = function(event)
{
	this.breakEvent = event;
	
	if ((this.breakEvent == 'GameBreak' && this.showMidroll) ||
		(this.breakEvent == 'GameEnd' && this.showPostroll))
	{
		var currentDate = new Date();
		var currentTime = currentDate.getTime();
		var interval = currentTime - this.lastShown;

		if (interval > this.wait*1000)
		{
			if (this.breakEvent == 'GameEnd')
				frames['spot'].location.href = this.postrollSrc;
			else
				frames['spot'].location.href = this.midrollSrc;

			this.adObject.style.visibility = 'visible';
			this.adObject.style.display = 'block';
			
			if (this.duration > 0)
			{
				this.countdown = this.duration+1;
				this.timer();
			}
			this.lastShown = currentTime;
			return;
		}
	}
	this.resumeGame();
}

adSpot.prototype.endDisplay = function()
{
	this.countdown = -1;

    frames['spot'].location.href = 'about:blank';

    this.adObject.style.visibility = 'hidden';
    this.adObject.style.display = 'none';

	if (this.showPreroll)
	{
		this.ownerContainer.style.visibility = 'visible';
		
		this.showPreroll = false;
		this.owner.hide = false;
		
		if (this.isOwnerLoaded)
			setTimeout('theAdSpot.owner.OnSessionReady("adCompleted")', 100);
	}
	else this.resumeGame();

    clearTimeout(this.globalTimer);
}

adSpot.prototype.canRunAsPreroll = function()
{

	if (!this.showPreroll) return false;
	if (this.isInIE) return true;
	
	try
	{
		var pluginType = 'application/x-popcaploader;version=1.0.0.1';
		mimetype = navigator.mimeTypes[pluginType];
			
		return (mimetype && mimetype.enabledPlugin && mimetype.type==pluginType);
	}
	catch (e) { return false; }

}

adSpot.prototype.runAsPreroll = function()
{
    var currentDate = new Date();
    var currentTime = currentDate.getTime();

    this.adObject.style.visibility = 'visible';
    this.adObject.style.display = 'block';

    if (this.duration > 0)
    {
        this.countdown = this.duration+1;
        this.timer();
    }
    this.lastShown = currentTime;
}

/******************************************************************************
*     INSTANTIATE GAME
*******************************************************************************/

thePopCapGame = new popCapAXGame("Bookworm Adventures",
	'GameObject',
	'540',
	'405',
	'BookwormAdventures',
	'bookwormadventures_1_1.cab');

/******************************************************************************
*     GAME PARAMETERS
*******************************************************************************/

thePopCapGame.paramNames[thePopCapGame.paramNames.length] ='params';
thePopCapGame.params[thePopCapGame.params.length] = 'ShowUpsell,Chapter2URL,Chapter3URL,Chapter4URL,focuspause,ZoneScript';

thePopCapGame.paramNames[thePopCapGame.paramNames.length] = 'ShowUpsell';
thePopCapGame.params[thePopCapGame.params.length] = Enable_Upsell ? 'true' : 'false';

thePopCapGame.paramNames[thePopCapGame.paramNames.length] = 'Chapter2URL';
thePopCapGame.params[thePopCapGame.params.length] = 'bwachapter2.cab';

thePopCapGame.paramNames[thePopCapGame.paramNames.length] = 'Chapter3URL';
thePopCapGame.params[thePopCapGame.params.length] = 'bwachapter3.cab';

thePopCapGame.paramNames[thePopCapGame.paramNames.length] = 'Chapter4URL';
thePopCapGame.params[thePopCapGame.params.length] = 'bwachapter4.cab';

thePopCapGame.paramNames[thePopCapGame.paramNames.length] = 'focuspause';
thePopCapGame.params[thePopCapGame.params.length] = 'true';

thePopCapGame.paramNames[thePopCapGame.paramNames.length] = 'ZoneScript';
thePopCapGame.params[thePopCapGame.params.length] = 'true';

/******************************************************************************
*     PARTNER-SPECIFIC SETTINGS
*******************************************************************************/

thePopCapGame.partnerName = 'PopCap';

// Instantiate ad and customize settings

theAdSpot = new adSpot('adlayer', thePopCapGame);

theAdSpot.width = Ad_Width;
theAdSpot.height = Ad_Height;
theAdSpot.ownerBgcolor = Game_BgColor;
theAdSpot.duration = Ad_Duration;
theAdSpot.showPreroll = Run_Preroll;
theAdSpot.showMidroll = Run_Midroll;
theAdSpot.showPostroll = Run_Postroll;
thePopCapGame.hide = Run_Preroll;

theAdSpot.wait = Min_Time_Between_Ads;
theAdSpot.prerollSrc = Preroll_Src_Path;
theAdSpot.midrollSrc = Midroll_Src_Path;
theAdSpot.postrollSrc = Postroll_Src_Path;

thePopCapGame.basePath = Base_Path;
thePopCapGame.upsellUrl = Upsell_Url;
  
thePopCapGame.logoCab = Logo_Cab_Path;
thePopCapGame.loaderCab = IE_Plugin_Path;
thePopCapGame.plugin = FireFox_Plugin_Path;

/*---- PARTNER-SPECIFIC SETTINGS : DOMAIN HASHES ----*/

thePopCapGame.hosts[thePopCapGame.hosts.length] = 'warrobotdoge.com';
thePopCapGame.signatures[thePopCapGame.signatures.length] = 'eSs5rbvVGcnTymSSJbMljS0DnlTjPdcySXHJTiFeCfo=';

thePopCapGame.hosts[thePopCapGame.hosts.length] = '*.popcappartner.com';
thePopCapGame.signatures[thePopCapGame.signatures.length] = 'nmMh/rMFAuytPzKoTESajn1j/2rQJXjMNXaoQaeGF1OXbk/9GC8kLJC3h4R6rcNMV+DTKF0jI6MavF/PuNSxy6frLJrZocmD8XNDWfIEWmsUdG8kJa2xp7z3oR9zhsDQYZbk2p9y4gEWiEEKjtBzPvNI5EEFnpHVFgYQVliYyiQ=';

thePopCapGame.hosts[thePopCapGame.hosts.length] = '*.popcap.com';
thePopCapGame.signatures[thePopCapGame.signatures.length] = 'ae5p6ROjz3ojd286Uj72ijgKPTMcD6zOPF+VOAOMeX8Jin4VtsjkhgtHoV4JIYGrJQsj4GnOND1UIpPkLvg0qj/zNhmMI5Sk+cvkmRqBkGwhIkLY/A8gy0e6V09rjmDATScvs66c0MziZ5n8mZv27gvuNK10xpEketmPm5tXQAE=';

thePopCapGame.hosts[thePopCapGame.hosts.length] = '*.internal.popcap.com';
thePopCapGame.signatures[thePopCapGame.signatures.length] = 'ciED+NlsqLQ2k+fTcYnl+NQpl+ckQdjGyadGv8pYNKNxvxCHIvA658nJgYpUDM3BEmwco9ggJiSbMzusI8lbvjsPj2CX3cqcUBarq44dXlBF1ou/VMLkSWcm9HUuuL0hnZFBnA3OCVPAQzVWOli6zawRVQmsIbxGh/xxkExTyJw=';



}
/*
     FILE ARCHIVED ON 05:54:29 Feb 28, 2023 AND RETRIEVED FROM THE
     INTERNET ARCHIVE ON 19:47:27 Jan 11, 2025.
     JAVASCRIPT APPENDED BY WAYBACK MACHINE, COPYRIGHT INTERNET ARCHIVE.

     ALL OTHER CONTENT MAY ALSO BE PROTECTED BY COPYRIGHT (17 U.S.C.
     SECTION 108(a)(3)).
*/
/*
playback timings (ms):
  captures_list: 0.528
  exclusion.robots: 0.021
  exclusion.robots.policy: 0.01
  esindex: 0.012
  cdx.remote: 138.956
  LoadShardBlock: 790.464 (3)
  PetaboxLoader3.resolve: 700.183 (4)
  PetaboxLoader3.datanode: 422.112 (4)
  load_resource: 458.161
*/