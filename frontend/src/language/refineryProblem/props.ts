/*
 * SPDX-FileCopyrightText: 2021-2023 The Refinery Authors <https://refinery.tools/>
 *
 * SPDX-License-Identifier: EPL-2.0
 */

import { NodeProp } from '@lezer/common';

export const implicitCompletion = new NodeProp({
  deserialize(s: string) {
    return s === 'true';
  },
});
