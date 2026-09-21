import Clutter from 'gi://Clutter?version=14';
import GObject from 'gi://GObject';
import Mtk from 'gi://Mtk?version=14';
const layout = new Mtk.Rectangle();
print(`Caller-allocated layout: ${layout.x},${layout.y} ${layout.width}x${layout.height}`);
GObject.type_class_ref(Clutter.Stage.$gtype);
for (const name of ['after-paint', 'presented']) {
    const id = GObject.signal_lookup(name, Clutter.Stage.$gtype);
    const query = GObject.signal_query(id);
    print(`${name}: ${query.param_types.map(type => GObject.type_name(type)).join(', ')}`);
}
