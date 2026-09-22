import unittest
from unittest.mock import Mock, patch

import mask_editor
from mask_editor import MaskEditor, canvas_rect_to_image, validate_rectangle_fields


class CanvasRectMappingTests(unittest.TestCase):
    def test_identity_mapping_uses_floor_and_ceil(self):
        self.assertEqual(
            canvas_rect_to_image(
                10.2,
                20.8,
                30.1,
                40.01,
                image_width=100,
                image_height=100,
                display_width=100,
                display_height=100,
                subsample_factor=1,
            ),
            (10, 20, 31, 41),
        )

    def test_reversed_drag_at_integer_subsample_scale(self):
        self.assertEqual(
            canvas_rect_to_image(
                500,
                300,
                100,
                50,
                image_width=2560,
                image_height=1440,
                display_width=854,
                display_height=480,
                subsample_factor=3,
            ),
            (300, 150, 1500, 900),
        )

    def test_outside_coordinates_are_clamped_to_image_bounds(self):
        self.assertEqual(
            canvas_rect_to_image(
                -25,
                -3,
                900,
                500,
                image_width=2560,
                image_height=1440,
                display_width=854,
                display_height=480,
                subsample_factor=3,
            ),
            (0, 0, 2560, 1440),
        )

    def test_actual_display_size_avoids_last_column_padding_error(self):
        self.assertEqual(
            canvas_rect_to_image(
                853,
                479,
                854,
                480,
                image_width=2560,
                image_height=1440,
                display_width=854,
                display_height=480,
                subsample_factor=3,
            ),
            (2559, 1437, 2560, 1440),
        )

    def test_invalid_dimensions_are_rejected(self):
        with self.assertRaises(ValueError):
            canvas_rect_to_image(
                0,
                0,
                1,
                1,
                image_width=0,
                image_height=10,
                display_width=10,
                display_height=10,
                subsample_factor=1,
            )

    def test_display_dimensions_must_match_subsample_factor(self):
        with self.assertRaises(ValueError):
            canvas_rect_to_image(
                0,
                0,
                1,
                1,
                image_width=2560,
                image_height=1440,
                display_width=853,
                display_height=480,
                subsample_factor=3,
            )


class RectangleFieldValidationTests(unittest.TestCase):
    def test_valid_integer_fields_return_half_open_rectangle(self):
        self.assertEqual(
            validate_rectangle_fields(
                (" 10 ", "20", "+30", "40"), image_width=100, image_height=80
            ),
            (10, 20, 30, 40),
        )

    def test_non_integer_field_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "x1 must be an integer"):
            validate_rectangle_fields(
                ("10", "20", "30.5", "40"), image_width=100, image_height=80
            )

    def test_out_of_bounds_field_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Coordinates must satisfy"):
            validate_rectangle_fields(
                ("0", "0", "101", "40"), image_width=100, image_height=80
            )

    def test_region_must_be_at_least_two_source_pixels(self):
        with self.assertRaisesRegex(ValueError, "at least 2"):
            validate_rectangle_fields(
                ("10", "20", "11", "40"), image_width=100, image_height=80
            )


class MaskEditorStateTests(unittest.TestCase):
    @staticmethod
    def _editor() -> MaskEditor:
        editor = MaskEditor.__new__(MaskEditor)
        editor.rectangles = [(10, 20, 30, 40)]
        editor._baseline_rectangles = [(10, 20, 30, 40)]
        editor._coordinate_index = 0
        editor.coordinate_vars = [
            Mock(get=Mock(return_value=value)) for value in ("10", "20", "30", "40")
        ]
        return editor

    def test_undo_back_to_loaded_baseline_is_not_dirty(self):
        editor = self._editor()
        self.assertFalse(editor._has_unsaved_changes())
        editor.rectangles = [(11, 20, 30, 40)]
        self.assertTrue(editor._has_unsaved_changes())
        editor.rectangles = list(editor._baseline_rectangles)
        self.assertFalse(editor._has_unsaved_changes())

    def test_unapplied_coordinate_text_is_dirty(self):
        editor = self._editor()
        editor.coordinate_vars[0].get.return_value = "12"
        self.assertTrue(editor._has_unsaved_changes())

    def test_cancel_stays_open_when_discard_is_declined(self):
        editor = self._editor()
        editor.rectangles.append((50, 50, 60, 60))
        editor._closed = False
        editor.window = Mock()
        editor._finish = Mock()
        dialogs = Mock()
        dialogs.askyesno.return_value = False
        with patch.object(mask_editor, "messagebox", dialogs):
            editor.cancel()
        dialogs.askyesno.assert_called_once()
        self.assertEqual(dialogs.askyesno.call_args.kwargs['default'], 'no')
        editor._finish.assert_not_called()

    def test_cancel_without_changes_does_not_prompt(self):
        editor = self._editor()
        editor._closed = False
        editor.window = Mock()
        editor._finish = Mock()
        dialogs = Mock()
        with patch.object(mask_editor, "messagebox", dialogs):
            editor.cancel()
        dialogs.askyesno.assert_not_called()
        editor._finish.assert_called_once()

    def test_apply_selected_records_undo_and_updates_rectangle(self):
        editor = self._editor()
        for variable, value in zip(editor.coordinate_vars, ("12", "22", "36", "48")):
            variable.get.return_value = value
        editor._image_width = 100
        editor._image_height = 80
        editor.notice_var = Mock()
        editor._undo_states = []
        editor._refresh_regions = Mock()
        self.assertTrue(editor._apply_selected_coordinates())
        self.assertEqual(editor.rectangles, [(12, 22, 36, 48)])
        self.assertEqual(editor._undo_states, [[(10, 20, 30, 40)]])
        editor._refresh_regions.assert_called_once_with(0)

    def test_apply_unchanged_normalizes_coordinate_text(self):
        editor = self._editor()
        editor.coordinate_vars[0].get.return_value = '0010'
        editor._image_width = 100
        editor._image_height = 80
        editor.notice_var = Mock()
        editor._show_selected_coordinates = Mock()
        self.assertTrue(editor._apply_selected_coordinates())
        editor._show_selected_coordinates.assert_called_once_with(0)

    def test_save_rejects_invalid_unapplied_coordinates(self):
        editor = self._editor()
        editor.coordinate_vars[2].get.return_value = "not an integer"
        editor._image_width = 100
        editor._image_height = 80
        editor._closed = False
        editor._capture_complete = True
        editor.notice_var = Mock()
        editor.controller = Mock()
        editor.target_dict = {}
        editor._save()
        editor.controller.save_mask_profile.assert_not_called()
        self.assertIn("must be an integer", editor.notice_var.set.call_args.args[0])

    def test_delete_and_undo_shortcuts_leave_focused_entry_alone(self):
        editor = self._editor()
        editor._delete_selected = Mock()
        editor._undo = Mock()
        focused = Mock()
        focused.winfo_class.return_value = "TEntry"
        editor.window = Mock()
        editor.window.focus_get.return_value = focused
        self.assertIsNone(editor._on_delete_key())
        self.assertIsNone(editor._on_undo_key())
        editor._delete_selected.assert_not_called()
        editor._undo.assert_not_called()

    @staticmethod
    def _selection_editor(coordinate_values: tuple[str, str, str, str]) -> MaskEditor:
        editor = MaskEditorStateTests._editor()
        editor.rectangles.append((50, 50, 70, 70))
        for variable, value in zip(editor.coordinate_vars, coordinate_values):
            variable.get.return_value = value
        editor._image_width = 100
        editor._image_height = 80
        editor._undo_states = []
        editor.notice_var = Mock()
        editor._refresh_regions = Mock()
        editor._selection_syncing = False
        editor.region_list = Mock()
        editor.region_list.curselection.return_value = (1,)
        editor.canvas = Mock()
        editor.delete_button = Mock()
        editor.coordinate_entries = [Mock() for _value in range(4)]
        editor.apply_button = Mock()
        return editor

    def test_valid_pending_coordinates_apply_before_selection_switch(self):
        editor = self._selection_editor(("12", "22", "36", "48"))
        with patch.object(mask_editor, "tk", Mock(END="end")):
            editor._on_list_selection()
        self.assertEqual(editor.rectangles[0], (12, 22, 36, 48))
        self.assertEqual(editor._undo_states, [[(10, 20, 30, 40), (50, 50, 70, 70)]])
        self.assertEqual(editor._coordinate_index, 1)
        editor.region_list.selection_set.assert_called_with(1)

    def test_invalid_pending_coordinates_block_selection_switch_and_keep_text(self):
        editor = self._selection_editor(("bad", "20", "30", "40"))
        with patch.object(mask_editor, "tk", Mock(END="end")):
            editor._on_list_selection()
        self.assertEqual(editor.rectangles[0], (10, 20, 30, 40))
        self.assertEqual(editor._coordinate_index, 0)
        editor.region_list.selection_set.assert_called_once_with(0)
        for variable in editor.coordinate_vars:
            variable.set.assert_not_called()
        self.assertIn("must be an integer", editor.notice_var.set.call_args.args[0])

    def test_reselecting_same_region_keeps_pending_text(self):
        editor = self._selection_editor(("bad", "20", "30", "40"))
        editor.region_list.curselection.return_value = (0,)
        editor._on_list_selection()
        for variable in editor.coordinate_vars:
            variable.set.assert_not_called()
        self.assertEqual(editor.rectangles[0], (10, 20, 30, 40))

    def test_malformed_loaded_profile_fails_closed(self):
        editor = MaskEditor.__new__(MaskEditor)
        editor.controller = Mock()
        editor.controller.load_mask_profile.return_value = {
            "width": 100,
            "height": 80,
            "rectangles": [[0, 0, 1, 10]],
        }
        editor.target_dict = {}
        editor._image_width = 100
        editor._image_height = 80
        editor.rectangles = []
        with self.assertRaisesRegex(ValueError, "out-of-bounds"):
            editor._load_profile()
        self.assertEqual(editor.rectangles, [])


if __name__ == "__main__":
    unittest.main()
