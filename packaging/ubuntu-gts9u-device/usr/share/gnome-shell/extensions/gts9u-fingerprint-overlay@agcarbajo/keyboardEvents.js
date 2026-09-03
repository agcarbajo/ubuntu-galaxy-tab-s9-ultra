// SPDX-License-Identifier: MIT
// GNOME 46 KeyboardManager calls keyboardBox.contains(actor) without checking
// whether stage.get_event_actor() returned null. This throws in native modal
// and unlock dialogs during input/layout transitions. A targetless event has
// no keyboard actor to dispatch to: return "not handled", never consume it.
export class KeyboardEventGuard {
    constructor(manager, getEventActor) {
        if (typeof manager?.maybeHandleEvent !== 'function')
            throw new Error('Unsupported native keyboard event handler');
        this._manager = manager;
        this._original = manager.maybeHandleEvent;
        this.targetlessEvents = 0;
        const guard = this;
        this._wrapper = function (event) {
            if (this.keyboardActor && getEventActor(event) == null) {
                guard.targetlessEvents++;
                return false;
            }
            return guard._original.call(this, event);
        };
        manager.maybeHandleEvent = this._wrapper;
    }

    destroy() {
        if (this._manager.maybeHandleEvent === this._wrapper)
            this._manager.maybeHandleEvent = this._original;
    }
}
