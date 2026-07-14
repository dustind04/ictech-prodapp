' icTech display channel.
'   First launch: picker (choice persists in the Roku registry).
'   After that: full-screen snapshot, refreshed every 4s with a
'   double-buffered swap. Press * (options) to re-pick the display.

sub init()
    m.posterA = m.top.findNode("posterA")
    m.posterB = m.top.findNode("posterB")
    m.status = m.top.findNode("status")
    m.picker = m.top.findNode("picker")
    m.pickerTitle = m.top.findNode("pickerTitle")
    m.timer = m.top.findNode("refresh")
    m.timer.observeField("fire", "onRefresh")
    m.count = 0
    m.showingA = false
    m.base = GetServerBase()
    m.keys = ["dashboard", "mb", "tech"]
    m.reg = CreateObject("roRegistrySection", "ictech")
    if m.reg.Exists("display")
        m.display = m.reg.Read("display")
        startDisplay()
    else
        showPicker()
    end if
end sub

sub showPicker()
    m.timer.control = "stop"
    m.posterA.visible = false
    m.posterB.visible = false
    content = CreateObject("roSGNode", "ContentNode")
    titles = ["Dashboard  (main backstage wall)", "Simple Micboard  (charger banks)", "Tech Dashboard  (patch / RF)"]
    for each t in titles
        node = content.createChild("ContentNode")
        node.title = t
    end for
    m.picker.content = content
    m.picker.observeField("itemSelected", "onPicked")
    m.picker.visible = true
    m.pickerTitle.visible = true
    m.picker.setFocus(true)
    m.status.text = "Server: " + m.base + "    (press * anytime to change display)"
end sub

sub onPicked()
    m.display = m.keys[m.picker.itemSelected]
    m.reg.Write("display", m.display)
    m.reg.Flush()
    m.picker.unobserveField("itemSelected")
    m.picker.visible = false
    m.pickerTitle.visible = false
    startDisplay()
end sub

sub startDisplay()
    m.status.text = "Loading " + m.display + " from " + m.base + " ..."
    m.timer.control = "start"
    onRefresh()
end sub

sub onRefresh()
    m.count = m.count + 1
    hidden = m.posterA
    if m.showingA then hidden = m.posterB
    hidden.observeField("loadStatus", "onLoaded")
    hidden.uri = m.base + "/snapshot/" + m.display + ".jpg?t=" + m.count.toStr()
end sub

sub onLoaded(event as Object)
    node = event.getRoSGNode()
    state = event.getData()
    if state = "ready"
        node.unobserveField("loadStatus")
        node.visible = true
        if node.id = "posterA"
            m.posterB.visible = false
            m.showingA = true
        else
            m.posterA.visible = false
            m.showingA = false
        end if
        m.status.text = ""
    else if state = "failed"
        node.unobserveField("loadStatus")
        m.status.text = "Can't reach " + m.base + "/snapshot/" + m.display + ".jpg — check the backstage PC"
    end if
end sub

function onKeyEvent(key as String, press as Boolean) as Boolean
    if press and key = "options"
        m.reg.Delete("display")
        m.reg.Flush()
        showPicker()
        return true
    end if
    return false
end function
