import { useState, type FormEvent } from "react";
import type { Group, Item } from "./data";

export function GroupEditor({
  group,
  items,
  onSave,
}: {
  group?: Group;
  items: Item[];
  onSave: (g: Group) => void;
}) {
  const [title, setTitle] = useState(group?.title ?? "");
  const [description, setDescription] = useState(group?.description ?? "");
  const [selected, setSelected] = useState(new Set(group?.itemIds ?? []));
  const [query, setQuery] = useState("");
  const matches = items.filter((i) =>
    `${i.title} ${i.type}`.toLowerCase().includes(query.toLowerCase()),
  );
  function submit(e: FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    // Preserve existing membership order; append new selections in picker order.
    const ordered = [
      ...(group?.itemIds ?? []).filter((id) => selected.has(id)),
      ...items
        .filter((i) => selected.has(i.id) && !group?.itemIds.includes(i.id))
        .map((i) => i.id),
    ];
    onSave({
      id: group?.id ?? `group-${crypto.randomUUID()}`,
      title: title.trim(),
      description: description.trim(),
      icon: group?.icon ?? "bookmark",
      itemIds: ordered,
    });
  }
  return (
    <form className="editor-form" onSubmit={submit}>
      <div className="modal-body editor-body">
        <label className="field">
          Group name
          <input
            data-initial-focus
            required
            maxLength={80}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            autoComplete="off"
          />
        </label>
        <label className="field">
          A little context <span className="muted">(optional)</span>
          <input
            maxLength={140}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>
        <fieldset className="membership">
          <legend>
            Items in this group{" "}
            <span className="muted">· {selected.size} selected</span>
          </legend>
          <p className="muted">
            Mix any kinds of knowledge. Removing an item here keeps it in your
            library.
          </p>
          <label className="field">
            Find items
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search example knowledge"
            />
          </label>
          <div className="membership-list">
            {matches.slice(0, 30).map((item) => (
              <label className="membership-row" key={item.id}>
                <input
                  type="checkbox"
                  checked={selected.has(item.id)}
                  onChange={(e) =>
                    setSelected((old) => {
                      const next = new Set(old);
                      if (e.target.checked) next.add(item.id);
                      else next.delete(item.id);
                      return next;
                    })
                  }
                />
                <span>
                  {item.title}
                  <small>{item.type}</small>
                </span>
              </label>
            ))}
          </div>
          {matches.length > 30 && (
            <p className="muted">
              Showing 30 of {matches.length} matches. Search to find a specific
              item.
            </p>
          )}
          {matches.length === 0 && (
            <p className="muted">No matching items. Try another word.</p>
          )}
        </fieldset>
      </div>
      <footer className="modal-footer">
        <button
          type="button"
          className="quiet-button"
          onClick={(e) => e.currentTarget.closest("dialog")?.close()}
        >
          Cancel
        </button>
        <button
          className="primary-button"
          type="submit"
          disabled={!title.trim()}
        >
          Save group
        </button>
      </footer>
    </form>
  );
}
